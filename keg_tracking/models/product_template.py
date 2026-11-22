from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    keg_type_id = fields.Many2one(
        'keg.type', string='Sold in Keg',
        help="Set this for draught products. Selling it dispatches returnable kegs of this type: "
             "a deposit line is added to the order and kegs are scanned when the order leaves. "
             "The product unit must be Units (one unit = one keg).")

    @api.constrains('keg_type_id', 'uom_id')
    def _check_keg_uom(self):
        unit = self.env.ref('uom.product_uom_unit')
        for product in self.filtered('keg_type_id'):
            if product.uom_id != unit:
                raise ValidationError(_(
                    "“%(product)s” is sold in kegs: its unit of measure must be “%(unit)s” "
                    "(one unit = one keg). Sales orders can still use other units of the same "
                    "category, such as dozens.",
                    product=product.display_name, unit=unit.name))
