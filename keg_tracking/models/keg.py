from collections import defaultdict
from datetime import timedelta

from markupsafe import Markup

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError

KEG_STATES = [
    ('available', 'Clean & Empty'),
    ('filled', 'Filled'),
    ('at_customer', 'At Customer'),
    ('to_clean', 'To Clean'),
    ('maintenance', 'Maintenance'),
    ('lost', 'Lost'),
    ('retired', 'Retired'),
]


class Keg(models.Model):
    _name = 'keg.keg'
    _description = 'Keg'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(string='Serial Number', required=True, copy=False, tracking=True, index='trigram')
    type_id = fields.Many2one(
        'keg.type', string='Keg Type', required=True, tracking=True, check_company=True,
        ondelete='restrict')
    company_id = fields.Many2one(
        'res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    state = fields.Selection(
        KEG_STATES, string='Status', required=True, default='available', tracking=True,
        readonly=True, index=True, copy=False, group_expand='_expand_states')
    product_id = fields.Many2one(
        'product.product', string='Beer', readonly=True, tracking=True, copy=False,
        help="Beer currently in the keg.")
    fill_date = fields.Date(readonly=True, copy=False)
    fill_count = fields.Integer(
        string='Fills', readonly=True, copy=False,
        help="Number of times this keg has been filled since it joined the fleet.")
    partner_id = fields.Many2one(
        'res.partner', string='Customer', readonly=True, tracking=True, index=True, copy=False,
        help="Delivery address currently holding the keg (or which lost it).")
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', readonly=True, copy=False)
    dispatch_date = fields.Date(readonly=True, copy=False)
    due_date = fields.Date(
        string='Expected Back', compute='_compute_due_date', store=True,
        help="Dispatch date plus the rotation target of the keg type.")
    days_at_customer = fields.Integer(compute='_compute_days_at_customer')
    is_overdue = fields.Boolean(
        string='Overdue', compute='_compute_days_at_customer', search='_search_is_overdue')
    deposit_amount_held = fields.Monetary(
        string='Deposit Held', readonly=True, copy=False,
        help="Deposit charged to the customer when this keg was dispatched; refunded on return.")
    acquisition_date = fields.Date(default=fields.Date.context_today)
    movement_ids = fields.One2many('keg.movement', 'keg_id', string='History')
    movement_count = fields.Integer(compute='_compute_movement_count')
    note = fields.Html(string='Notes')

    _sql_constraints = [
        ('name_company_uniq', 'unique(name, company_id)', "This serial number is already used by another keg."),
    ]

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends('state', 'dispatch_date', 'type_id.max_days_at_customer')
    def _compute_due_date(self):
        for keg in self:
            if keg.state == 'at_customer' and keg.dispatch_date:
                keg.due_date = keg.dispatch_date + timedelta(days=keg.type_id.max_days_at_customer)
            else:
                keg.due_date = False

    @api.depends('state', 'dispatch_date', 'due_date')
    def _compute_days_at_customer(self):
        today = fields.Date.context_today(self)
        for keg in self:
            at_customer = keg.state == 'at_customer' and keg.dispatch_date
            keg.days_at_customer = (today - keg.dispatch_date).days if at_customer else 0
            keg.is_overdue = bool(at_customer and keg.due_date and keg.due_date < today)

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_("Unsupported search on overdue kegs."))
        today = fields.Date.context_today(self)
        overdue_domain = [('state', '=', 'at_customer'), ('due_date', '<', today)]
        positive = (operator == '=') == value
        return overdue_domain if positive else ['!', '&'] + overdue_domain

    def _expand_states(self, states, domain):
        # Show the whole operational cycle as kanban columns, even when empty.
        return [key for key, _label in KEG_STATES if key not in ('lost', 'retired')] + \
            [s for s in states if s in ('lost', 'retired')]

    def _compute_movement_count(self):
        counts = dict(self.env['keg.movement']._read_group(
            [('keg_id', 'in', self.ids)], ['keg_id'], ['__count']))
        for keg in self:
            keg.movement_count = counts.get(keg, 0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _state_label(self, state):
        return dict(self._fields['state']._description_selection(self.env))[state]

    def _ensure_state(self, allowed_states, operation):
        wrong = self.filtered(lambda keg: keg.state not in allowed_states)
        if wrong:
            raise UserError(_(
                "%(operation)s is only possible for kegs that are %(states)s.\n\n%(kegs)s",
                operation=operation,
                states=_(" or ").join(self._state_label(s) for s in allowed_states),
                kegs="\n".join(f"• {keg.name} ({self._state_label(keg.state)})" for keg in wrong),
            ))

    def _ensure_manager(self):
        if not self.env.user.has_group('keg_tracking.group_keg_manager'):
            raise AccessError(_("Only keg managers can perform this operation."))

    def _log_movement(self, movement_type, **values):
        return self.env['keg.movement'].create([{
            'keg_id': keg.id,
            'movement_type': movement_type,
            'partner_id': keg.partner_id.id,
            'product_id': keg.product_id.id,
            **values,
        } for keg in self])

    @api.model
    def _find_by_serial(self, serial):
        serial = (serial or '').strip()
        if not serial:
            return self.browse()
        return self.search([('name', '=ilike', serial)], limit=1)

    # ------------------------------------------------------------------
    # Workflow
    # ------------------------------------------------------------------

    def _fill(self, product):
        self._ensure_state(['available'], _("Filling"))
        if not product.keg_type_id:
            raise UserError(_("“%s” is not sold in kegs. Set a keg type on the product first.",
                              product.display_name))
        wrong_type = self.filtered(lambda keg: keg.type_id != product.keg_type_id)
        if wrong_type:
            raise UserError(_(
                "“%(product)s” is packaged in %(type)s kegs. These kegs are of another type:\n%(kegs)s",
                product=product.display_name, type=product.keg_type_id.name,
                kegs=", ".join(wrong_type.mapped('name'))))
        today = fields.Date.context_today(self)
        for keg in self:
            keg.write({
                'state': 'filled',
                'product_id': product.id,
                'fill_date': today,
                'fill_count': keg.fill_count + 1,
            })
        self._log_movement('fill')

    def _dispatch(self, sale_line, **movement_values):
        self._ensure_state(['filled'], _("Dispatch"))
        wrong_beer = self.filtered(lambda keg: keg.product_id != sale_line.product_id)
        if wrong_beer:
            raise UserError(_(
                "These kegs do not contain “%(product)s”:\n%(kegs)s",
                product=sale_line.product_id.display_name,
                kegs="\n".join(f"• {k.name} ({k.product_id.display_name})" for k in wrong_beer)))
        order = sale_line.order_id
        for keg in self:
            keg.write({
                'state': 'at_customer',
                'partner_id': order.partner_shipping_id.id,
                'sale_order_id': order.id,
                'dispatch_date': fields.Date.context_today(self),
                'deposit_amount_held': keg.type_id.deposit_amount,
            })
        self._log_movement('dispatch', sale_order_id=order.id, sale_line_id=sale_line.id, **movement_values)

    def _register_return(self, refund_deposit=True):
        """Bring kegs back from customers. Returns the draft deposit credit notes created."""
        self._ensure_state(['at_customer'], _("Return"))
        refunds, refund_by_keg = self.env['account.move'], {}
        if refund_deposit:
            refunds, refund_by_keg = self.filtered('deposit_amount_held')._create_customer_documents('out_refund')
        for keg in self:
            keg._log_movement(
                'return', sale_order_id=keg.sale_order_id.id, move_id=refund_by_keg.get(keg.id, False))
        self.write({
            'state': 'to_clean',
            'partner_id': False,
            'sale_order_id': False,
            'dispatch_date': False,
            'deposit_amount_held': 0.0,
            'product_id': False,
        })
        return refunds

    def _declare_lost(self, charge_customer=True, note=False):
        """Declare kegs lost at the customer. Returns the draft invoices created."""
        self._ensure_manager()
        self._ensure_state(['at_customer'], _("Declaring a keg lost"))
        invoices, invoice_by_keg = self.env['account.move'], {}
        if charge_customer:
            chargeable = self.filtered(lambda k: k.type_id.replacement_value > k.deposit_amount_held)
            invoices, invoice_by_keg = chargeable._create_customer_documents('out_invoice')
        for keg in self:
            keg._log_movement(
                'lost', sale_order_id=keg.sale_order_id.id, move_id=invoice_by_keg.get(keg.id, False),
                note=note)
        # The customer keeps the custody link (who lost it); the deposit is retained.
        self.write({'state': 'lost', 'product_id': False})
        return invoices

    def _create_customer_documents(self, move_type):
        """Create one draft deposit refund (out_refund) or lost-keg invoice (out_invoice) per customer.

        :return: (created moves, {keg id: move id})
        """
        if not self:
            return self.env['account.move'], {}
        kegs_by_customer = defaultdict(lambda: self.browse())
        for keg in self:
            kegs_by_customer[(keg.partner_id.commercial_partner_id, keg.company_id)] |= keg

        move_vals_list, kegs_per_move = [], []
        for (customer, company), kegs in kegs_by_customer.items():
            if move_type == 'out_refund':
                lines = kegs._prepare_deposit_refund_lines()
            else:
                lines = kegs._prepare_loss_invoice_lines()
            move_vals_list.append({
                'move_type': move_type,
                'partner_id': customer.id,
                'company_id': company.id,
                'currency_id': company.currency_id.id,
                'invoice_origin': ", ".join(sorted(set(kegs.sale_order_id.mapped('name')))) or False,
                'invoice_line_ids': lines,
            })
            kegs_per_move.append(kegs)
        # Operators are not necessarily accountants: documents are created as drafts for review.
        moves = self.env['account.move']
        for vals in move_vals_list:
            moves |= self.env['account.move'].with_company(vals['company_id']).sudo().create(vals)
        moves = moves.with_env(self.env)
        move_by_keg = {keg.id: move.id for move, kegs in zip(moves, kegs_per_move) for keg in kegs}
        return moves, move_by_keg

    def _prepare_deposit_refund_lines(self):
        groups = defaultdict(lambda: self.browse())
        for keg in self:
            groups[(keg.type_id, keg.deposit_amount_held)] |= keg
        return [
            Command.create({
                'product_id': keg_type.deposit_product_id.id,
                'name': _("Deposit refund – %(type)s – returned kegs: %(serials)s",
                          type=keg_type.name, serials=", ".join(kegs.mapped('name'))),
                'quantity': len(kegs),
                'price_unit': amount,
            })
            for (keg_type, amount), kegs in groups.items()
        ]

    def _prepare_loss_invoice_lines(self):
        return [
            Command.create({
                'product_id': keg.type_id.loss_product_id.id,
                'name': _("Unreturned keg %(serial)s (%(type)s, dispatched %(date)s): replacement "
                          "value %(value)s minus deposit retained %(deposit)s",
                          serial=keg.name, type=keg.type_id.name,
                          date=keg.dispatch_date and fields.Date.to_string(keg.dispatch_date) or '-',
                          value=keg.type_id.replacement_value, deposit=keg.deposit_amount_held),
                'quantity': 1,
                'price_unit': keg.type_id.replacement_value - keg.deposit_amount_held,
            })
            for keg in self
        ]

    @api.model
    def _action_done(self, message, moves=None):
        """Wizard result: open the accounting documents created (for invoicing users), else notify."""
        moves = moves or self.env['account.move']
        if moves and self.env.user.has_group('account.group_account_invoice'):
            xmlid = ('account.action_move_out_refund_type' if moves[0].move_type == 'out_refund'
                     else 'account.action_move_out_invoice_type')
            action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
            if len(moves) == 1:
                action.update({'res_id': moves.id, 'views': [(False, 'form')], 'view_mode': 'form'})
            else:
                action['domain'] = [('id', 'in', moves.ids)]
            return action
        if moves:
            message += " " + _("%s draft document(s) were prepared for the accounting team.", len(moves))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': message,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------

    def action_mark_cleaned(self):
        self._ensure_state(['to_clean'], _("Cleaning"))
        self._log_movement('clean')
        self.write({'state': 'available'})

    def action_send_to_maintenance(self):
        self._ensure_state(['available', 'to_clean', 'filled'], _("Maintenance"))
        self._log_movement('maintenance')
        self.write({'state': 'maintenance', 'product_id': False})

    def action_back_in_service(self):
        self._ensure_state(['maintenance'], _("Putting back in service"))
        self._log_movement('repaired')
        # A repaired keg must go through the washing line before it can be filled.
        self.write({'state': 'to_clean'})

    def action_mark_recovered(self):
        self._ensure_manager()
        self._ensure_state(['lost'], _("Recovering"))
        for keg in self:
            loss = keg.movement_ids.filtered(lambda m: m.movement_type == 'lost')[:1]
            keg._log_movement('recovered')
            if loss.move_id:
                keg.message_post(body=Markup(_(
                    "Keg recovered. The customer was charged for its loss on %s: "
                    "issue a credit note if it should be reimbursed.")) % loss.move_id._get_html_link())
        self.write({
            'state': 'to_clean',
            'partner_id': False,
            'sale_order_id': False,
            'dispatch_date': False,
            'deposit_amount_held': 0.0,
        })

    def action_retire(self):
        self._ensure_manager()
        self._ensure_state(['available', 'to_clean', 'maintenance', 'lost'], _("Retiring"))
        self._log_movement('retire')
        self.write({'state': 'retired', 'product_id': False})

    def action_open_fill_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Fill Kegs"),
            'res_model': 'keg.fill.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_keg_ids': self.filtered(lambda k: k.state == 'available').ids},
        }

    def action_open_return_wizard(self):
        customers = self.partner_id.commercial_partner_id
        if len(customers) > 1:
            raise UserError(_("Register returns one customer at a time."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Return Kegs"),
            'res_model': 'keg.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_partner_id': customers.id,
                'default_keg_ids': self.filtered(lambda k: k.state == 'at_customer').ids,
            },
        }

    def action_open_lost_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Declare Kegs Lost"),
            'res_model': 'keg.lost.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_keg_ids': self.ids},
        }

    def action_view_movements(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('keg_tracking.action_keg_movement')
        action['domain'] = [('keg_id', '=', self.id)]
        action['context'] = {'search_default_keg_id': self.id}
        return action

    # ------------------------------------------------------------------
    # Automation
    # ------------------------------------------------------------------

    @api.model
    def _cron_notify_overdue_kegs(self):
        """Schedule (or refresh) one reminder per customer holding overdue kegs."""
        activity_type = self.env.ref('keg_tracking.mail_activity_type_overdue_kegs')
        overdue = self.search([('is_overdue', '=', True)])
        kegs_by_customer = defaultdict(lambda: self.browse())
        for keg in overdue:
            kegs_by_customer[keg.partner_id.commercial_partner_id] |= keg

        admin = self.env.ref('base.user_admin', raise_if_not_found=False)
        for customer, kegs in kegs_by_customer.items():
            items = Markup()
            for keg in kegs.sorted('dispatch_date'):
                items += Markup("<li>%s</li>") % _(
                    "%(serial)s – %(type)s – %(days)s days (expected back %(due)s)",
                    serial=keg.name, type=keg.type_id.name, days=keg.days_at_customer,
                    due=fields.Date.to_string(keg.due_date))
            note = Markup("<p>%s</p><ul>%s</ul>") % (
                _("These kegs are past their rotation target. Please arrange a pickup:"), items)
            summary = _("%s overdue keg(s) to collect", len(kegs))
            existing = self.env['mail.activity'].search([
                ('res_model', '=', 'res.partner'),
                ('res_id', '=', customer.id),
                ('activity_type_id', '=', activity_type.id),
            ], limit=1)
            if existing:
                existing.write({'note': note, 'summary': summary})
                continue
            user = customer.user_id or kegs.partner_id.user_id[:1] or admin
            customer.activity_schedule(
                activity_type_id=activity_type.id, summary=summary, note=note,
                user_id=user.id if user else self.env.uid)
