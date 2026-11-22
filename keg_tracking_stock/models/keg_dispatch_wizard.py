from odoo import _, models
from odoo.exceptions import UserError


class KegDispatchWizard(models.TransientModel):
    _inherit = 'keg.dispatch.wizard'

    def _check_can_dispatch(self):
        super()._check_can_dispatch()
        # Dispatching outside the delivery would desynchronise stock and keg custody.
        if self.sale_order_id.picking_ids.filtered(lambda p: p.picking_type_code == 'outgoing'):
            raise UserError(_(
                "%s is delivered through Inventory: scan the kegs on its delivery order instead.",
                self.sale_order_id.name))
