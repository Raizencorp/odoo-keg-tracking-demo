from datetime import timedelta

from psycopg2 import IntegrityError

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged
from odoo.tools import mute_logger

from .common import KegTrackingCommon


@tagged('post_install', '-at_install')
class TestKegWorkflow(KegTrackingCommon):

    # Configuration --------------------------------------------------------------------

    def test_replacement_value_cannot_be_below_deposit(self):
        with self.assertRaises(ValidationError):
            self.keg_type_20.replacement_value = 20.0

    @mute_logger('odoo.sql_db')
    def test_serial_number_is_unique(self):
        with self.assertRaises(IntegrityError):
            self.env['keg.keg'].create({'name': 'K20-001', 'type_id': self.keg_type_20.id})

    # Deposit lines ----------------------------------------------------------------------

    def test_deposit_lines_follow_draught_lines(self):
        order = self._create_order([(self.ipa, 2), (self.blonde, 1)], confirm=False)
        deposits = order.order_line.filtered('deposit_keg_type_id')
        self.assertEqual(len(deposits), 2, "One deposit line per keg type")
        dep_20 = deposits.filtered(lambda l: l.deposit_keg_type_id == self.keg_type_20)
        self.assertEqual((dep_20.product_uom_qty, dep_20.price_unit), (2, 30.0))

        # Two beers in the same keg type share one deposit line.
        order.order_line = [fields.Command.create({'product_id': self.stout.id, 'product_uom_qty': 3})]
        self.assertEqual(dep_20.product_uom_qty, 5)
        self.assertEqual(dep_20.price_unit, 30.0, "Quantity change must not reset the deposit price")

        # Removing the 30 L beer removes its deposit from the quotation.
        order.order_line.filtered(lambda l: l.product_id == self.blonde).unlink()
        self.assertEqual(order.order_line.filtered('deposit_keg_type_id').deposit_keg_type_id, self.keg_type_20)

    def test_keg_quantities_in_other_units(self):
        dozen = self.env.ref('uom.product_uom_dozen')
        order = self._create_order([(self.ipa, 1)], confirm=False)
        line = order.order_line.filtered(lambda l: l.product_id == self.ipa)
        line.write({'product_uom': dozen.id, 'product_uom_qty': 0.5})
        self.assertEqual(order.order_line.filtered('deposit_keg_type_id').product_uom_qty, 6)
        order.action_confirm()
        self.assertEqual(order.keg_ordered_qty, 6)
        self._dispatch(order, {self.ipa: self._filled(self.kegs_20[:3], self.ipa)})
        self.assertEqual(order.keg_dispatch_status, 'partial')
        self.assertAlmostEqual(line.qty_delivered, 0.25, msg="3 kegs = a quarter of a dozen")
        with self.assertRaisesRegex(ValidationError, 'whole number of kegs'):
            line.product_uom_qty = 0.6  # 7.2 kegs

    def test_draught_product_must_be_counted_in_units(self):
        with self.assertRaisesRegex(ValidationError, 'one unit = one keg'):
            self.env['product.product'].create({
                'name': 'Stout by the dozen', 'type': 'consu', 'keg_type_id': self.keg_type_20.id,
                'uom_id': self.env.ref('uom.product_uom_dozen').id,
                'uom_po_id': self.env.ref('uom.product_uom_dozen').id,
            })

    # Filling ----------------------------------------------------------------------------

    def test_fill_rules(self):
        keg = self.kegs_20[0]
        with self.assertRaisesRegex(UserError, 'packaged in'):
            keg._fill(self.blonde)
        keg._fill(self.ipa)
        self.assertEqual((keg.state, keg.product_id, keg.fill_count), ('filled', self.ipa, 1))
        with self.assertRaisesRegex(UserError, 'only possible'):
            keg._fill(self.ipa)

    def test_fill_wizard_scan(self):
        with Form(self.env['keg.fill.wizard']) as wizard:
            wizard.product_id = self.ipa
            wizard.scan = ' k20-002 '
            wizard.scan = 'K30-001'  # wrong type: rejected with a warning
            self.assertEqual(wizard.keg_ids.ids, self.kegs_20[1].ids)
            self.assertFalse(wizard.scan, "The scan field is cleared for the next scan")
        wizard.record.action_confirm()
        self.assertEqual(self.kegs_20[1].state, 'filled')

    # Dispatch ---------------------------------------------------------------------------

    def test_dispatch_and_invoice(self):
        order = self._create_order([(self.ipa, 2)])
        self.assertEqual(order.keg_dispatch_status, 'to_dispatch')
        kegs = self._filled(self.kegs_20[:2], self.ipa)
        self._dispatch(order, {self.ipa: kegs})

        self.assertEqual(set(kegs.mapped('state')), {'at_customer'})
        self.assertEqual(kegs.partner_id, order.partner_shipping_id)
        self.assertEqual(kegs.mapped('deposit_amount_held'), [30.0, 30.0])
        self.assertEqual(kegs[0].due_date, fields.Date.context_today(kegs) + timedelta(days=45))
        self.assertEqual(order.keg_dispatch_status, 'dispatched')
        self.assertEqual(order.keg_held_count, 2)

        beer_line = order.order_line.filtered(lambda l: l.product_id == self.ipa)
        deposit_line = order.order_line.filtered('deposit_keg_type_id')
        self.assertEqual(beer_line.qty_delivered, 2)
        self.assertEqual(deposit_line.qty_delivered, 2)

        invoice = order._create_invoices()
        self.assertEqual(
            sorted((l.product_id, l.quantity) for l in invoice.invoice_line_ids),
            sorted([(self.ipa, 2), (self.deposit_product, 2)]))

    def test_partial_dispatch_invoices_only_what_left(self):
        order = self._create_order([(self.ipa, 3)])
        self._dispatch(order, {self.ipa: self._filled(self.kegs_20[:1], self.ipa)})
        self.assertEqual(order.keg_dispatch_status, 'partial')
        invoice = order._create_invoices()
        self.assertEqual(set(invoice.invoice_line_ids.mapped('quantity')), {1.0})

    def test_dispatch_controls(self):
        order = self._create_order([(self.ipa, 1)])
        with self.assertRaisesRegex(UserError, 'only 1 left'):
            self._dispatch(order, {self.ipa: self._filled(self.kegs_20[:2], self.ipa)})
        stout_keg = self._filled(self.kegs_20[2], self.stout)
        with self.assertRaisesRegex(UserError, 'do not contain'):
            stout_keg._dispatch(order.order_line.filtered(lambda l: l.product_id == self.ipa))
        with self.assertRaisesRegex(UserError, 'only possible'):
            self.kegs_20[3]._dispatch(order.order_line[0])  # empty keg

    def test_dispatch_wizard_scan(self):
        order = self._create_order([(self.ipa, 1), (self.stout, 1)])
        self._filled(self.kegs_20[0], self.ipa)
        self._filled(self.kegs_20[1:3], self.stout)
        wizard_form = Form(self.env['keg.dispatch.wizard'].with_context(default_sale_order_id=order.id))
        wizard_form.scan = 'K20-002'
        wizard_form.scan = 'K20-003'  # second stout: order only needs one
        wizard_form.scan = 'K20-001'
        wizard = wizard_form.save()
        self.assertEqual(wizard.line_ids.keg_ids, self.kegs_20[:2])
        wizard.action_confirm()
        self.assertEqual(order.keg_dispatch_status, 'dispatched')

    def test_ordered_quantity_cannot_drop_below_dispatched(self):
        order = self._create_order([(self.ipa, 2)])
        self._dispatch(order, {self.ipa: self._filled(self.kegs_20[:2], self.ipa)})
        with self.assertRaises(ValidationError):
            order.order_line.filtered(lambda l: l.product_id == self.ipa).product_uom_qty = 1

    def test_cannot_cancel_order_with_kegs_out(self):
        order = self._create_order([(self.ipa, 1)])
        self._dispatch(order, {self.ipa: self._filled(self.kegs_20[0], self.ipa)})
        with self.assertRaisesRegex(UserError, 'still at the customer'):
            order.with_context(disable_cancel_warning=True).action_cancel()
        self.kegs_20[0]._register_return()
        order.with_context(disable_cancel_warning=True).action_cancel()
        self.assertEqual(order.state, 'cancel')

    # Return -----------------------------------------------------------------------------

    def test_return_refunds_deposit_actually_held(self):
        order = self._create_order([(self.ipa, 2)])
        kegs = self._filled(self.kegs_20[:2], self.ipa)
        self._dispatch(order, {self.ipa: kegs})
        self.keg_type_20.deposit_amount = 35.0  # price change after dispatch

        wizard = self.env['keg.return.wizard'].create({
            'partner_id': self.customer.id, 'keg_ids': [fields.Command.set(kegs.ids)]})
        self.assertEqual(wizard.deposit_total, 60.0)
        wizard.action_confirm()

        refund = kegs.movement_ids.filtered(lambda m: m.movement_type == 'return').move_id
        self.assertEqual(len(refund), 1)
        self.assertEqual((refund.move_type, refund.state), ('out_refund', 'draft'))
        self.assertEqual(refund.partner_id, self.customer)
        self.assertAlmostEqual(refund.amount_total, 60.0)
        self.assertEqual(set(kegs.mapped('state')), {'to_clean'})
        self.assertFalse(kegs.partner_id)
        self.assertEqual(order.keg_held_count, 0)

        kegs.action_mark_cleaned()
        self.assertEqual(set(kegs.mapped('state')), {'available'})

    def test_return_wizard_rejects_other_customer_kegs(self):
        order = self._create_order([(self.ipa, 1)], partner=self.partner_b)
        self._dispatch(order, {self.ipa: self._filled(self.kegs_20[0], self.ipa)})
        wizard = Form(self.env['keg.return.wizard'].with_context(default_partner_id=self.customer.id))
        wizard.scan = 'K20-001'
        self.assertFalse(wizard.keg_ids)
        # Scanning first selects the customer automatically.
        wizard = Form(self.env['keg.return.wizard'])
        wizard.scan = 'K20-001'
        self.assertEqual(wizard.partner_id, self.partner_b)
        self.assertEqual(len(wizard.keg_ids), 1)

    # Overdue & losses -------------------------------------------------------------------

    def test_overdue_detection_and_single_reminder(self):
        order = self._create_order([(self.ipa, 2)])
        kegs = self._filled(self.kegs_20[:2], self.ipa)
        self._dispatch(order, {self.ipa: kegs})
        self.assertFalse(kegs[0].is_overdue)
        kegs[0].dispatch_date = fields.Date.context_today(kegs) - timedelta(days=50)
        self.assertTrue(kegs[0].is_overdue)
        self.assertEqual(kegs[0].days_at_customer, 50)
        self.assertEqual(self.env['keg.keg'].search([('is_overdue', '=', True)]), kegs[0])
        self.assertIn(kegs[1], self.env['keg.keg'].search([('is_overdue', '=', False)]))

        activity_type = self.env.ref('keg_tracking.mail_activity_type_overdue_kegs')
        Keg = self.env['keg.keg']
        Keg._cron_notify_overdue_kegs()
        Keg._cron_notify_overdue_kegs()
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'res.partner'), ('res_id', '=', self.customer.id),
            ('activity_type_id', '=', activity_type.id)])
        self.assertEqual(len(activities), 1, "A customer gets one open reminder, refreshed daily")
        self.assertIn('K20-001', activities.note)
        self.assertEqual(self.customer.keg_overdue_count, 1)
        self.assertEqual(self.customer.keg_count, 2)
        self.assertEqual(self.customer.keg_deposit_held, 60.0)

    def test_lost_keg_charges_replacement_minus_deposit(self):
        order = self._create_order([(self.ipa, 1), (self.blonde, 1)])
        keg_20 = self._filled(self.kegs_20[0], self.ipa)
        keg_30 = self._filled(self.kegs_30[0], self.blonde)
        self._dispatch(order, {self.ipa: keg_20, self.blonde: keg_30})

        wizard = self.env['keg.lost.wizard'].create({
            'keg_ids': [fields.Command.set((keg_20 | keg_30).ids)], 'reason': 'Bar closed down'})
        self.assertEqual(wizard.charge_total, (140 - 30) + (165 - 40))
        wizard.action_confirm()

        invoice = (keg_20 | keg_30).movement_ids.filtered(lambda m: m.movement_type == 'lost').move_id
        self.assertEqual(len(invoice), 1, "One invoice per customer")
        self.assertEqual(sorted(invoice.invoice_line_ids.mapped('price_unit')), [110.0, 125.0])
        self.assertEqual(set((keg_20 | keg_30).mapped('state')), {'lost'})
        self.assertEqual(keg_20.partner_id, order.partner_shipping_id, "We keep who lost the keg")

        keg_20.action_mark_recovered()
        self.assertEqual(keg_20.state, 'to_clean')
        self.assertFalse(keg_20.partner_id)

    def test_maintenance_cycle(self):
        keg = self._filled(self.kegs_20[0], self.ipa)
        keg.action_send_to_maintenance()
        self.assertEqual((keg.state, keg.product_id.id), ('maintenance', False))
        keg.action_back_in_service()
        self.assertEqual(keg.state, 'to_clean', "A repaired keg is washed before reuse")
        keg.action_retire()
        self.assertEqual(keg.state, 'retired')
        self.assertEqual(
            keg.movement_ids.mapped('movement_type'), ['retire', 'repaired', 'maintenance', 'fill'])
