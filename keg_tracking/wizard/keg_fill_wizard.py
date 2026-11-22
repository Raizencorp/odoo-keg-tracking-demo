from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KegFillWizard(models.TransientModel):
    _name = 'keg.fill.wizard'
    _description = 'Fill Kegs'

    product_id = fields.Many2one(
        'product.product', string='Beer', required=True,
        domain="[('keg_type_id', '!=', False), ('sale_ok', '=', True)]")
    keg_type_id = fields.Many2one(related='product_id.keg_type_id')
    scan = fields.Char(string='Scan Serial', help="Scan or type a keg serial number and press Enter.")
    keg_ids = fields.Many2many(
        'keg.keg', string='Kegs',
        domain="[('state', '=', 'available'), ('type_id', '=', keg_type_id)]")

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.keg_ids = self.keg_ids.filtered(lambda k: k.type_id == self.keg_type_id)

    @api.onchange('scan')
    def _onchange_scan(self):
        if not self.scan:
            return
        serial, self.scan = self.scan, False
        keg = self.env['keg.keg']._find_by_serial(serial)
        if not keg:
            return {'warning': {'title': _("Unknown keg"), 'message': _("No keg with serial “%s”.", serial)}}
        if keg.state != 'available':
            return {'warning': {'title': _("Keg not ready"), 'message': _(
                "Keg %(serial)s is %(state)s: only clean and empty kegs can be filled.",
                serial=keg.name, state=keg._state_label(keg.state))}}
        if self.product_id and keg.type_id != self.keg_type_id:
            return {'warning': {'title': _("Wrong keg type"), 'message': _(
                "Keg %(serial)s is a %(keg_type)s keg; %(beer)s is packaged in %(expected)s kegs.",
                serial=keg.name, keg_type=keg.type_id.name, beer=self.product_id.display_name,
                expected=self.keg_type_id.name)}}
        self.keg_ids |= keg

    def action_confirm(self):
        self.ensure_one()
        if not self.keg_ids:
            raise UserError(_("Scan or select at least one keg to fill."))
        self.keg_ids._fill(self.product_id)
        return self.env['keg.keg']._action_done(_(
            "%(count)s keg(s) filled with %(beer)s.", count=len(self.keg_ids), beer=self.product_id.display_name))
