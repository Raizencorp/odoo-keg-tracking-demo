from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests import new_test_user, tagged

from .common import KegTrackingCommon


@tagged('post_install', '-at_install')
class TestKegSecurity(KegTrackingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        company = cls.env.company
        cls.salesman = new_test_user(
            cls.env, login='keg_sales', groups='sales_team.group_sale_salesman',
            company_id=company.id, company_ids=[company.id])
        # Cellar operator: no sales nor accounting rights.
        cls.operator = new_test_user(
            cls.env, login='keg_operator', groups='base.group_user,keg_tracking.group_keg_operator',
            company_id=company.id, company_ids=[company.id])

    def test_salesman_sees_kegs_but_cannot_operate(self):
        keg = self.kegs_20[0].with_user(self.salesman)
        self.assertEqual(keg.state, 'available')
        with self.assertRaises(AccessError):
            keg._fill(self.ipa)

    def test_operator_runs_the_daily_workflow(self):
        order = self._create_order([(self.ipa, 2)])
        kegs = self.kegs_20[:2].with_user(self.operator)
        self.env['keg.fill.wizard'].with_user(self.operator).create({
            'product_id': self.ipa.id, 'keg_ids': [fields.Command.set(kegs.ids)]}).action_confirm()
        self._dispatch(order, {self.ipa: kegs}, user=self.operator)
        self.assertEqual(order.order_line.filtered(lambda l: l.product_id == self.ipa).qty_delivered, 2)

        action = self.env['keg.return.wizard'].with_user(self.operator).create({
            'partner_id': self.customer.id, 'keg_ids': [fields.Command.set(kegs.ids)]}).action_confirm()
        # Without accounting rights the operator is notified instead of opening the credit note.
        self.assertEqual(action['tag'], 'display_notification')
        self.assertTrue(kegs.sudo().movement_ids.filtered(lambda m: m.movement_type == 'return').move_id)

    def test_operator_restrictions(self):
        order = self._create_order([(self.ipa, 1)])
        keg = self._filled(self.kegs_20[0], self.ipa)
        self._dispatch(order, {self.ipa: keg})
        keg = keg.with_user(self.operator)
        with self.assertRaises(AccessError):
            keg._declare_lost()
        with self.assertRaises(AccessError):
            self.keg_type_20.with_user(self.operator).deposit_amount = 0
        with self.assertRaises(AccessError):
            keg.movement_ids.write({'note': 'tampered'})
        with self.assertRaises(AccessError):
            keg.movement_ids.unlink()
