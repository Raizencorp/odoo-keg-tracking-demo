import unittest

from odoo import Command

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class KegTrackingCommon(AccountTestInvoicingCommon):
    # Tests of the sales-only flow (kegs dispatched from the sales order). With Inventory,
    # keg_tracking_stock dispatches from delivery orders and has its own tests.
    sales_only_flow = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if cls.sales_only_flow and cls.env['ir.module.module']._get('sale_stock').state == 'installed':
            raise unittest.SkipTest("Sales-only keg flow: covered by keg_tracking_stock when Inventory is installed")
        # The accounting test user also runs the brewery: sales and keg management rights.
        cls.env.user.groups_id |= (
            cls.env.ref('sales_team.group_sale_manager') | cls.env.ref('keg_tracking.group_keg_manager'))
        Product = cls.env['product.product']
        cls.deposit_product = Product.create({
            'name': 'Keg Deposit', 'type': 'service', 'invoice_policy': 'delivery',
            'taxes_id': [Command.clear()], 'sale_ok': False,
        })
        cls.loss_product = Product.create({
            'name': 'Unreturned Keg', 'type': 'service', 'invoice_policy': 'order', 'sale_ok': False,
        })
        cls.keg_type_20 = cls.env['keg.type'].create({
            'name': 'Keg 20 L', 'capacity': 20, 'deposit_amount': 30.0, 'replacement_value': 140.0,
            'max_days_at_customer': 45,
            'deposit_product_id': cls.deposit_product.id, 'loss_product_id': cls.loss_product.id,
        })
        cls.keg_type_30 = cls.env['keg.type'].create({
            'name': 'Keg 30 L', 'capacity': 30, 'deposit_amount': 40.0, 'replacement_value': 165.0,
            'max_days_at_customer': 60,
            'deposit_product_id': cls.deposit_product.id, 'loss_product_id': cls.loss_product.id,
        })
        cls.ipa = Product.create({
            'name': 'IPA keg 20 L', 'type': 'consu', 'invoice_policy': 'delivery', 'list_price': 90.0,
            'keg_type_id': cls.keg_type_20.id,
        })
        cls.stout = Product.create({
            'name': 'Stout keg 20 L', 'type': 'consu', 'invoice_policy': 'delivery', 'list_price': 92.0,
            'keg_type_id': cls.keg_type_20.id,
        })
        cls.blonde = Product.create({
            'name': 'Blonde keg 30 L', 'type': 'consu', 'invoice_policy': 'delivery', 'list_price': 98.0,
            'keg_type_id': cls.keg_type_30.id,
        })
        cls.customer = cls.partner_a
        cls.kegs_20 = cls.env['keg.keg'].create([
            {'name': f'K20-{n:03d}', 'type_id': cls.keg_type_20.id} for n in range(1, 7)])
        cls.kegs_30 = cls.env['keg.keg'].create([
            {'name': f'K30-{n:03d}', 'type_id': cls.keg_type_30.id} for n in range(1, 4)])

    def _create_order(self, lines, partner=None, confirm=True):
        order = self.env['sale.order'].create({
            'partner_id': (partner or self.customer).id,
            'order_line': [Command.create({'product_id': product.id, 'product_uom_qty': qty})
                           for product, qty in lines],
        })
        if confirm:
            order.action_confirm()
        return order

    def _dispatch(self, order, kegs_by_product, user=None):
        wizard = self.env['keg.dispatch.wizard']
        if user:
            wizard = wizard.with_user(user)
        wizard = wizard.with_context(default_sale_order_id=order.id).create({})
        for line in wizard.line_ids:
            kegs = kegs_by_product.get(line.product_id)
            if kegs:
                line.keg_ids = kegs
        return wizard.action_confirm()

    def _filled(self, kegs, product):
        kegs._fill(product)
        return kegs
