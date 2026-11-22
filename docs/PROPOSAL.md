# Design Notes: Use Case Selection and Architecture

## 1. Candidate business problems

| # | Candidate | Target business | What standard Odoo (Community 18) lacks | Business value | Technical depth | Portfolio potential |
|---|-----------|-----------------|------------------------------------------|----------------|-----------------|---------------------|
| A | **Returnable keg tracking & deposit management** | Craft breweries, cider makers, beverage wholesalers | No per-container custody tracking, no deposit lifecycle (charge → refund → retain), no loss charging, no ageing of assets held by customers | **High** — kegs cost €100–180 each; small breweries typically lose 5–10 % of their fleet per year and tie up cash in idle kegs | Custody state machine, Sales & Accounting integration, scheduled automation, scanning UX | **High** — concrete, instantly understandable, measurable ROI |
| B | Equipment rental with damage inspection | Event / tool rental companies | Rental is Enterprise-only | Medium–high | Medium | Low — reproduces an existing (Enterprise) app |
| C | 8D customer complaint handling | Small manufacturers (ISO 9001) | Quality app is Enterprise-only; Helpdesk is not a CAPA process | Medium | Medium (mostly forms + stages) | Medium — workflow-heavy but little integration |
| D | Subcontractor tender / bid comparison | Construction SMEs | Purchase RFQ comparison exists (`purchase_requisition`) | Medium | Medium | Low — overlaps standard features |
| E | Food lot recall campaigns | Food producers | Lot traceability exists; recall comms do not | High but rare event | High (needs full Inventory) | Medium — hard to demo convincingly without heavy setup |

## 2. Selected concept: **A — Returnable Keg Tracking**

### Why
* **Real, recurring, costly problem.** A brewery's keg fleet is one of its largest fixed assets. Kegs leave the
  brewery full and are supposed to come back empty, but bars hoard them, swap them, or lose them. Without
  tracking per serial number nobody can say *which* customer holds *which* keg, since *when*, or what deposit
  is owed back.
* **Standard Odoo does not cover it.** The usual workaround is a "deposit" product added manually to orders
  and a spreadsheet for the kegs. Nothing links a physical keg to a customer, a deposit, or a refund.
* **Extends Odoo rather than replacing it.** Sales orders, invoices, credit notes, customers, products,
  activities and the chatter are all reused. The module only adds the part that is missing: the keg itself.
* **Right size.** A complete, coherent workflow fits into one focused module.

### Target business (demo scenario)
**Brasserie des Aiguilles** — a fictional independent craft brewery near Annecy (Haute-Savoie). 3 beers on
draught, a fleet of ~450 stainless kegs (20 L and 30 L), ~70 customers: bars, restaurants, a ski resort,
an events caterer.

### Users and responsibilities
| Role | Odoo group | Responsibilities |
|------|-----------|------------------|
| Sales rep | Sales / User + **Kegs: Viewer** (implied) | Sells draught beer, sees kegs held by each customer, gets an activity when a customer sits on overdue kegs |
| Cellar / logistics operator | **Kegs: Operator** | Cleans and fills kegs, scans kegs onto delivery orders, scans returned empties |
| Brewery manager / accountant | **Kegs: Manager** | Configures keg types and deposit rules, declares lost kegs and bills them, retires damaged kegs |

### Workflow — before
1. Order taken in Odoo; deposit line added by hand (often forgotten).
2. Driver writes keg numbers on paper — or doesn't.
3. Returned empties counted, not identified; deposit refunds negotiated from memory.
4. Once a year the fleet is counted: 30 kegs "missing", nobody knows where, nobody is billed.

### Workflow — after
```
            Fill (scan)            Dispatch on sales order (scan)
 Clean & Empty ───────▶ Filled ───────────────────────────────▶ At Customer
       ▲                                                          │   │
       │ Clean                         Return (scan) + deposit    │   │ Overdue → activity to sales rep
       │                               credit note (draft)        │   │ Declare lost → invoice
   To Clean ◀─────────────────────────────────────────────────────┘   ▼   (replacement − deposit)
       ▲  ▲                                                          Lost
       │  └──── Back in service ── Maintenance ◀── (damaged)          │ Recovered
       └──────────────────────────────────────────────────────────────┘
                      Any idle state ──(manager)──▶ Retired
```
* **Confirming** a sales order changes nothing physical — only dispatch does.
* **Dispatch** (scan serials against the order lines) moves kegs into the customer's custody, records the
  deposit held per keg, adds/updates a *deposit line* on the order, and sets the delivered quantity of the
  beer line, so standard *Create Invoice* bills exactly what left the brewery.
* **Return** (scan serials at the customer) puts kegs back in *To Clean* and drafts a credit note refunding the
  exact deposits held for those serials.
* **Daily automation** flags kegs held beyond the keg type's rotation target and schedules one activity per
  customer for the sales rep.
* **Loss declaration** bills the customer the replacement value minus the deposit already retained.

### Business value
* Every keg has a known location and history → fewer losses, fleet sized on facts.
* Deposits are charged systematically and refunded exactly → no revenue leakage, no disputes.
* Lost kegs become an invoice, not a write-off.
* Sales reps get actionable reminders instead of an annual surprise.

## 3. Architecture

### Dependencies
`sale_management` (brings `sale`, `account`, `mail`). Deliberately **no `stock` dependency** in the core
module: many small breweries invoice from sales orders without the Inventory app, and kegs are
custody-tracked *assets*, not stock. Breweries using Inventory get the `keg_tracking_stock` bridge
(`auto_install`): kegs are then scanned on the delivery order, and validating it dispatches them.

### Models
| Model | Kind | Purpose |
|-------|------|---------|
| `keg.type` | new | Container format: capacity, deposit, replacement value, rotation target, deposit & loss products |
| `keg.keg` | new (mail.thread) | One physical keg (serial). Custody state machine, current beer, customer, dispatch date, deposit held |
| `keg.movement` | new | Immutable audit log of every state change (fill, dispatch, return, clean, …), linked to order / invoice |
| `product.template` | extended | `keg_type_id`: "this beer is sold in kegs of type X" |
| `sale.order` / `sale.order.line` | extended | Dispatch status, dispatched kegs, automatic deposit lines, cancellation guard |
| `res.partner` | extended | Kegs held, overdue kegs, deposit held; smart button; "Return Kegs" |
| `keg.fill.wizard`, `keg.dispatch.wizard`, `keg.return.wizard`, `keg.lost.wizard` | transient | Scanning-friendly operations |

### Business rules
* A serial number is unique per company.
* Only *Clean & Empty* kegs can be filled, and only with a beer packaged in that keg type.
* Only *Filled* kegs containing the ordered beer can be dispatched on an order line; never more than ordered.
* An order line quantity cannot be reduced below what was already dispatched; an order with kegs still at the
  customer cannot be cancelled.
* Deposit refunded on return = deposit actually held for that serial (price changes don't corrupt refunds).
* Loss charge = replacement value − deposit held (never negative; enforced on keg type).
* Overdue = at customer longer than the keg type's rotation target. One open reminder per customer at most.

### Security
* Groups: *Viewer* ⊂ *Operator* ⊂ *Manager*; Sales users imply *Viewer*.
* Movements are append-only for operators; only managers can configure keg types or declare losses.
* Multi-company record rules on kegs, keg types and movements.
* Accounting documents created by operators (deposit credit notes) are created as **drafts** for review.

### Views
Kanban (grouped by status) and list of kegs, keg form with status bar / ribbons / history / chatter, pivot &
graph for fleet analysis, movement log, keg type configuration with stat buttons, smart buttons on sales order
and customer, "Dispatch Kegs" button on the order, scanning wizards.
