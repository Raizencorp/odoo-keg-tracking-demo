from datetime import timedelta

from odoo import api, fields, models


class KegDemo(models.Model):
    _inherit = 'keg.keg'

    @api.model
    def _demo_load_scenario(self):
        """Build the demonstration fleet and ~7 months of history.

        Called from demo data only. Every step goes through the real workflow methods
        (fill, dispatch, return, loss, cleaning, invoicing); dates are then shifted into the
        past so that rotation ageing and overdue reminders can be demonstrated.
        """
        if self.search_count([]):
            return
        self = self.with_company(self.env.ref('keg_tracking.company_brewery'))
        env = self.env
        ref = env.ref
        now = fields.Datetime.now()
        last_movement = [max(env['keg.movement'].search([]).ids or [0])]

        def ago(days):
            return now - timedelta(days=days)

        def stamp(days):
            new = env['keg.movement'].search([('id', '>', last_movement[0])])
            if new:
                new.write({'date': ago(days)})
                last_movement[0] = max(new.ids)

        def kegs(*serials):
            return self.search([('name', 'in', serials)])

        def fill(product_xmlid, serials, days):
            batch = kegs(*serials)
            batch._fill(ref(product_xmlid))
            batch.write({'fill_date': ago(days).date()})
            stamp(days)

        def confirm(order_xmlid, days):
            order = ref(order_xmlid)
            order.action_confirm()
            order.date_order = ago(days)
            return order

        def dispatch(order, product_xmlid, serials, days):
            product = ref(product_xmlid)
            batch = kegs(*serials)
            delivery = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel')) \
                if 'picking_ids' in order._fields else False
            line = order.order_line.filtered(lambda l: l.product_id == product)
            if delivery:
                # Inventory installed: the kegs leave with a validated delivery order.
                for move in delivery.move_ids:
                    shipped = len(batch) if move.product_id == product else 0
                    move.write({'quantity': shipped, 'picked': bool(shipped)})
                bridge_loaded = 'keg_ids' in delivery._fields  # keg_tracking_stock dispatches on validation
                if bridge_loaded:
                    delivery.keg_ids = batch
                delivery.with_context(cancel_backorder=False)._action_done()
                delivery.date_done = ago(days)
                if not bridge_loaded:
                    batch._dispatch(line)
            else:
                batch._dispatch(line)
            batch.write({'dispatch_date': ago(days).date()})
            stamp(days)

        def invoice(order, days):
            move = order._create_invoices()
            move.invoice_date = ago(days).date()
            move.action_post()

        def give_back(serials, days, post=True):
            refunds = kegs(*serials)._register_return()
            refunds.invoice_date = ago(days).date()
            if post:
                refunds.action_post()
            stamp(days)

        def clean(serials, days):
            kegs(*serials).action_mark_cleaned()
            stamp(days)

        # Fleet: 14 kegs of each size, bought last year.
        type_20, type_30 = ref('keg_tracking.keg_type_20l'), ref('keg_tracking.keg_type_30l')
        self.create(
            [{'name': f'AIG30-{n:03d}', 'type_id': type_30.id, 'acquisition_date': ago(400).date()}
             for n in range(1, 15)]
            + [{'name': f'AIG20-{n:03d}', 'type_id': type_20.id, 'acquisition_date': ago(400).date()}
               for n in range(1, 15)])

        # Summer wedding (caterer): one keg came back, the other never did.
        fill('keg_tracking.product_stout_20l', ['AIG20-011', 'AIG20-012'], 201)
        order = confirm('keg_tracking.sale_order_traiteur_summer', 200)
        dispatch(order, 'keg_tracking.product_stout_20l', ['AIG20-011', 'AIG20-012'], 199)
        invoice(order, 199)
        give_back(['AIG20-011'], 170)
        clean(['AIG20-011'], 169)

        # Le Comptoir du Lac: regular customer sitting on four kegs for 75 days.
        fill('keg_tracking.product_blonde_30l', ['AIG30-001', 'AIG30-002', 'AIG30-003', 'AIG30-004'], 77)
        fill('keg_tracking.product_ipa_20l', ['AIG20-001', 'AIG20-002'], 77)
        order = confirm('keg_tracking.sale_order_comptoir', 76)
        dispatch(order, 'keg_tracking.product_blonde_30l', ['AIG30-001', 'AIG30-002', 'AIG30-003', 'AIG30-004'], 75)
        dispatch(order, 'keg_tracking.product_ipa_20l', ['AIG20-001', 'AIG20-002'], 75)
        invoice(order, 75)
        give_back(['AIG30-001', 'AIG30-002'], 40)
        clean(['AIG30-001'], 39)

        # Dented keg taken out of the fleet.
        kegs('AIG30-014').action_retire()
        stamp(120)

        # Restaurant Le Belvédère: delivered three weeks ago, not invoiced yet.
        fill('keg_tracking.product_blonde_30l', ['AIG30-005', 'AIG30-006', 'AIG30-007'], 22)
        fill('keg_tracking.product_stout_20l', ['AIG20-003', 'AIG20-004', 'AIG20-005'], 22)
        order = confirm('keg_tracking.sale_order_belvedere', 21)
        dispatch(order, 'keg_tracking.product_blonde_30l', ['AIG30-005', 'AIG30-006', 'AIG30-007'], 20)
        dispatch(order, 'keg_tracking.product_stout_20l', ['AIG20-003', 'AIG20-004', 'AIG20-005'], 20)

        # Caterer's summer keg written off after months of reminders.
        kegs('AIG20-012')._declare_lost(
            note="Left at the wedding venue, venue manager cannot find it")
        stamp(15)

        # Leaking spear found during cleaning.
        kegs('AIG30-013').action_send_to_maintenance()
        stamp(10)

        # Ski-resort bar: season opening, 4 of 6 kegs delivered, 1 more filled and waiting.
        order = confirm('keg_tracking.sale_order_altitude', 3)
        fill('keg_tracking.product_blonde_30l', ['AIG30-008', 'AIG30-009', 'AIG30-010', 'AIG30-011'], 3)
        dispatch(order, 'keg_tracking.product_blonde_30l', ['AIG30-008', 'AIG30-009', 'AIG30-010', 'AIG30-011'], 2)
        fill('keg_tracking.product_blonde_30l', ['AIG30-012'], 1)

        # Caterer's winter seminar: confirmed, kegs filled, ready to load.
        confirm('keg_tracking.sale_order_traiteur_winter', 1)
        fill('keg_tracking.product_ipa_20l', ['AIG20-006', 'AIG20-007'], 1)

        # Le Cerf-Volant stays a quotation (deposit lines already visible on it).

        # First run of the daily reminder.
        self._cron_notify_overdue_kegs()
