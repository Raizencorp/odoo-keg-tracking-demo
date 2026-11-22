from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_compare


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    keg_movement_ids = fields.One2many('keg.movement', 'sale_order_id', string='Keg Movements')
    keg_ordered_qty = fields.Integer(compute='_compute_keg_dispatch', store=True, string='Kegs Ordered')
    keg_dispatched_qty = fields.Integer(compute='_compute_keg_dispatch', store=True, string='Kegs Dispatched')
    keg_dispatch_status = fields.Selection([
        ('to_dispatch', 'To Dispatch'),
        ('partial', 'Partially Dispatched'),
        ('dispatched', 'Dispatched'),
    ], string='Keg Dispatch', compute='_compute_keg_dispatch', store=True,
        help="Physical dispatch of the draught kegs of this order.")
    keg_held_count = fields.Integer(
        compute='_compute_keg_held_count', string='Kegs Still Out',
        help="Kegs of this order that the customer has not returned yet.")

    @api.depends('state', 'order_line.product_uom_qty', 'order_line.product_uom', 'order_line.keg_dispatched_qty',
                 'order_line.product_id.keg_type_id')
    def _compute_keg_dispatch(self):
        for order in self:
            keg_lines = order.order_line.filtered('keg_type_id')
            ordered = round(sum(line._get_keg_quantity() for line in keg_lines))
            dispatched = sum(keg_lines.mapped('keg_dispatched_qty'))
            order.keg_ordered_qty = ordered
            order.keg_dispatched_qty = dispatched
            if not keg_lines or order.state != 'sale':
                order.keg_dispatch_status = False
            elif dispatched >= ordered:
                order.keg_dispatch_status = 'dispatched'
            elif dispatched:
                order.keg_dispatch_status = 'partial'
            else:
                order.keg_dispatch_status = 'to_dispatch'

    def _compute_keg_held_count(self):
        counts = dict(self.env['keg.keg']._read_group(
            [('sale_order_id', 'in', self.ids), ('state', '=', 'at_customer')],
            ['sale_order_id'], ['__count']))
        for order in self:
            order.keg_held_count = counts.get(order, 0)

    def _sync_keg_deposit_lines(self):
        """One deposit line per keg type: quantity = kegs ordered, price = deposit of the type."""
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        for order in self.with_context(keg_deposit_sync=True):
            if order.state == 'cancel' or order.locked:
                continue
            required = defaultdict(float)
            for line in order.order_line.filtered(lambda l: l.keg_type_id and not l.display_type):
                required[line.keg_type_id] += round(line._get_keg_quantity())
            deposit_lines = {line.deposit_keg_type_id: line
                             for line in order.order_line if line.deposit_keg_type_id}
            sequence = max(order.order_line.mapped('sequence') or [10]) + 1
            to_create = []
            for keg_type, qty in required.items():
                line = deposit_lines.pop(keg_type, None)
                if not line:
                    to_create.append({
                        'order_id': order.id,
                        'product_id': keg_type.deposit_product_id.id,
                        'name': _("Keg deposit – %s", keg_type.name),
                        'product_uom_qty': qty,
                        'price_unit': keg_type.deposit_amount,
                        'deposit_keg_type_id': keg_type.id,
                        'sequence': sequence,
                    })
                    sequence += 1
                    continue
                vals = {}
                if float_compare(line.product_uom_qty, qty, precision_digits=precision):
                    vals['product_uom_qty'] = qty
                # Always rewrite the price with the quantity: otherwise the pricelist recomputes it.
                if not line.qty_invoiced and (vals or line.currency_id.compare_amounts(
                        line.price_unit, keg_type.deposit_amount)):
                    vals['price_unit'] = keg_type.deposit_amount
                if vals:
                    line.write(vals)
            # Draught lines removed: drop their deposit line (or reduce it once confirmed).
            for line in deposit_lines.values():
                if order.state in ('draft', 'sent'):
                    line.unlink()
                else:
                    line.product_uom_qty = line.keg_dispatched_qty
            if to_create:
                self.env['sale.order.line'].with_context(keg_deposit_sync=True).create(to_create)

    def action_confirm(self):
        self._sync_keg_deposit_lines()
        return super().action_confirm()

    def _action_cancel(self):
        blocked = self.env['keg.keg'].search(
            [('sale_order_id', 'in', self.ids), ('state', '=', 'at_customer')]).sale_order_id
        if blocked:
            raise UserError(_(
                "Kegs dispatched on %s are still at the customer. Register their return "
                "(or declare them lost) before cancelling the order.",
                ", ".join(blocked.mapped('name'))))
        return super()._action_cancel()

    def action_open_keg_dispatch(self):
        self.ensure_one()
        if self.state != 'sale':
            raise UserError(_("Confirm the order before dispatching kegs."))
        if self.keg_dispatch_status not in ('to_dispatch', 'partial'):
            raise UserError(_("All the kegs of this order have already been dispatched."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("Dispatch Kegs – %s", self.name),
            'res_model': 'keg.dispatch.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_sale_order_id': self.id},
        }

    def action_view_kegs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('keg_tracking.action_keg')
        action.update({
            'name': _("Kegs of %s", self.name),
            'domain': [('id', 'in', self.keg_movement_ids.keg_id.ids)],
            'context': {'create': False},
            'views': [(False, 'list'), (False, 'form')],
            'view_mode': 'list,form',
        })
        return action
