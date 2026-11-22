from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare, float_round


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    keg_type_id = fields.Many2one(related='product_id.keg_type_id', string='Keg Type')
    deposit_keg_type_id = fields.Many2one(
        'keg.type', string='Deposit for Keg Type', readonly=True, index='btree_not_null',
        help="Set on the deposit lines managed automatically by keg tracking.")
    keg_movement_ids = fields.One2many('keg.movement', 'sale_line_id', string='Keg Movements')
    keg_dispatched_qty = fields.Integer(
        string='Kegs Dispatched', compute='_compute_keg_dispatched_qty', store=True)

    @api.depends('keg_movement_ids', 'deposit_keg_type_id', 'order_id.keg_movement_ids')
    def _compute_keg_dispatched_qty(self):
        for line in self:
            if line.deposit_keg_type_id:
                movements = line.order_id.keg_movement_ids.filtered(
                    lambda m: m.movement_type == 'dispatch' and m.type_id == line.deposit_keg_type_id)
            else:
                movements = line.keg_movement_ids.filtered(lambda m: m.movement_type == 'dispatch')
            line.keg_dispatched_qty = len(movements)

    def _get_keg_quantity(self):
        """Number of kegs ordered on this line, whatever unit of measure the line uses.

        Draught products are always stocked in Units (see product constraint), so the line
        quantity converted to the product unit is a number of kegs.
        """
        self.ensure_one()
        if not self.keg_type_id or self.display_type:
            return 0.0
        return self.product_uom._compute_quantity(
            self.product_uom_qty, self.product_id.uom_id, rounding_method='HALF-UP')

    def _get_keg_remaining(self):
        """Kegs still to dispatch on this line."""
        self.ensure_one()
        return max(round(self._get_keg_quantity()) - self.keg_dispatched_qty, 0)

    @api.depends('keg_dispatched_qty', 'product_uom')
    def _compute_qty_delivered(self):
        # Without the Inventory app, the delivered quantity of draught beer and deposits is
        # what has actually been scanned out of the brewery.
        keg_lines = self.filtered(
            lambda l: l.qty_delivered_method == 'manual' and (l.keg_type_id or l.deposit_keg_type_id))
        for line in keg_lines:
            line.qty_delivered = line.product_id.uom_id._compute_quantity(
                line.keg_dispatched_qty, line.product_uom, round=False)
        return super(SaleOrderLine, self - keg_lines)._compute_qty_delivered()

    @api.constrains('product_uom_qty', 'product_uom', 'keg_dispatched_qty')
    def _check_keg_quantity(self):
        for line in self.filtered('keg_type_id'):
            kegs = line._get_keg_quantity()
            if float_compare(kegs, float_round(kegs, precision_digits=0), precision_digits=3):
                raise ValidationError(_(
                    "“%(product)s” is sold by the keg: %(qty)s %(uom)s is %(kegs)s kegs. "
                    "Enter a quantity corresponding to a whole number of kegs.",
                    product=line.product_id.display_name, qty=line.product_uom_qty,
                    uom=line.product_uom.name, kegs=round(kegs, 3)))
            if float_compare(kegs, line.keg_dispatched_qty, precision_digits=3) < 0:
                raise ValidationError(_(
                    "%(kegs)s kegs of “%(product)s” have already been dispatched on %(order)s: "
                    "the ordered quantity cannot be lower.",
                    kegs=line.keg_dispatched_qty, product=line.product_id.display_name,
                    order=line.order_id.name))

    # Keep deposit lines in sync with draught lines --------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._sync_keg_deposits()
        return lines

    def write(self, vals):
        if not ({'product_id', 'product_uom_qty', 'product_uom'} & set(vals)) or self.env.context.get('keg_deposit_sync'):
            return super().write(vals)
        # Include orders whose line stops being a draught product.
        orders = self.filtered('keg_type_id').order_id
        res = super().write(vals)
        (orders | self.filtered('keg_type_id').order_id)._sync_keg_deposit_lines()
        return res

    def unlink(self):
        orders = self.filtered('keg_type_id').order_id
        res = super().unlink()
        if not self.env.context.get('keg_deposit_sync'):
            orders.exists()._sync_keg_deposit_lines()
        return res

    def _sync_keg_deposits(self):
        if self.env.context.get('keg_deposit_sync'):
            return
        self.filtered('keg_type_id').order_id._sync_keg_deposit_lines()
