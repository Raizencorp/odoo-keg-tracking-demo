from odoo import _, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _get_pending_keg_deliveries(self):
        return self.picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state not in ('done', 'cancel')
            and p._get_keg_moves())

    def action_open_keg_dispatch(self):
        """With Inventory, kegs are scanned on the delivery order."""
        self.ensure_one()
        deliveries = self._get_pending_keg_deliveries()
        if not deliveries:
            return super().action_open_keg_dispatch()
        action = self.env['ir.actions.act_window']._for_xml_id('stock.action_picking_tree_all')
        if len(deliveries) == 1:
            action.update({'res_id': deliveries.id, 'views': [(False, 'form')], 'view_mode': 'form'})
        else:
            action['domain'] = [('id', 'in', deliveries.ids)]
        action['name'] = _("Deliveries of %s", self.name)
        action['context'] = {}
        return action
