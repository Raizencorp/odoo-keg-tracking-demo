from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.keg_tracking.tests.common import KegTrackingCommon


@tagged('post_install', '-at_install')
class TestKegStock(KegTrackingCommon):
    sales_only_flow = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env.user.groups_id |= cls.env.ref('stock.group_stock_manager')

    def _delivery(self, order):
        picking = order.picking_ids.filtered(lambda p: p.state not in ('done', 'cancel'))
        self.assertEqual(len(picking), 1)
        return picking

    def test_delivery_cannot_be_validated_without_kegs(self):
        order = self._create_order([(self.ipa, 2)])
        picking = self._delivery(order)
        self.assertEqual(picking.keg_expected_qty, 2)
        with self.assertRaisesRegex(UserError, 'scan the kegs'):
            picking.button_validate()
        self.assertEqual(order.keg_dispatch_status, 'to_dispatch')

    def test_delivery_dispatches_scanned_kegs(self):
        order = self._create_order([(self.ipa, 2), (self.blonde, 1)])
        ipa_kegs = self._filled(self.kegs_20[:2], self.ipa)
        blonde_keg = self._filled(self.kegs_30[0], self.blonde)
        self._filled(self.kegs_20[2], self.stout)
        picking = self._delivery(order)

        with Form(picking) as picking_form:
            for serial in ('K20-001', 'K20-003', 'k30-001', 'K20-002', 'K20-001'):
                picking_form.keg_scan = serial  # K20-003 (stout) and the duplicate are refused
        self.assertEqual(picking.keg_ids, ipa_kegs | blonde_keg)

        picking.button_validate()
        self.assertEqual(picking.state, 'done')
        self.assertEqual(set((ipa_kegs | blonde_keg).mapped('state')), {'at_customer'})
        self.assertEqual(ipa_kegs.movement_ids.filtered(lambda m: m.movement_type == 'dispatch').picking_id, picking)
        self.assertEqual(order.keg_dispatch_status, 'dispatched')
        ipa_line = order.order_line.filtered(lambda l: l.product_id == self.ipa)
        self.assertEqual(ipa_line.qty_delivered_method, 'stock_move')
        self.assertEqual(ipa_line.qty_delivered, 2)
        deposits = order.order_line.filtered('deposit_keg_type_id')
        self.assertEqual(sorted(deposits.mapped('qty_delivered')), [1, 2])

    def test_partial_delivery_with_backorder(self):
        order = self._create_order([(self.ipa, 3)])
        picking = self._delivery(order)
        keg = self._filled(self.kegs_20[0], self.ipa)
        picking.move_ids.write({'quantity': 1, 'picked': True})
        picking.keg_ids = keg
        picking.with_context(cancel_backorder=False)._action_done()

        self.assertEqual(keg.state, 'at_customer')
        self.assertEqual(order.keg_dispatch_status, 'partial')
        backorder = self._delivery(order)
        self.assertEqual(backorder.keg_expected_qty, 2)

    def test_sales_order_dispatch_goes_through_delivery(self):
        order = self._create_order([(self.ipa, 1)])
        action = order.action_open_keg_dispatch()
        self.assertEqual((action['res_model'], action['res_id']), ('stock.picking', order.picking_ids.id))
        keg = self._filled(self.kegs_20[0], self.ipa)
        with self.assertRaisesRegex(UserError, 'delivery order'):
            self._dispatch(order, {self.ipa: keg})
