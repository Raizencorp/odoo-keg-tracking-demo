from collections import defaultdict

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    keg_ids = fields.Many2many(
        'keg.keg', 'stock_picking_keg_rel', 'picking_id', 'keg_id', string='Kegs Loaded', copy=False,
        domain="[('state', '=', 'filled'), ('product_id', 'in', keg_product_ids)]",
        help="Filled kegs loaded on the truck for this delivery. They are dispatched to the "
             "customer when the delivery is validated.")
    keg_scan = fields.Char(
        string='Scan Keg', store=False, help="Scan or type a keg serial number and press Enter.")
    keg_product_ids = fields.Many2many('product.product', compute='_compute_keg_info')
    keg_expected_qty = fields.Integer(compute='_compute_keg_info', string='Kegs to Load')
    keg_loaded_count = fields.Integer(compute='_compute_keg_info', string='Kegs Scanned')
    keg_movement_ids = fields.One2many('keg.movement', 'picking_id', string='Keg Movements')

    def _get_keg_moves(self):
        return self.move_ids.filtered(
            lambda m: m.sale_line_id.keg_type_id and m.state not in ('done', 'cancel'))

    @api.depends('move_ids.product_uom_qty', 'move_ids.state', 'keg_ids', 'picking_type_code')
    def _compute_keg_info(self):
        for picking in self:
            moves = picking._get_keg_moves() if picking.picking_type_code == 'outgoing' else self.env['stock.move']
            picking.keg_product_ids = moves.product_id
            picking.keg_expected_qty = round(sum(
                m.product_uom._compute_quantity(m.product_uom_qty, m.product_id.uom_id) for m in moves))
            picking.keg_loaded_count = len(picking.keg_ids)

    @api.onchange('keg_scan')
    def _onchange_keg_scan(self):
        if not self.keg_scan:
            return
        serial, self.keg_scan = self.keg_scan, False
        keg = self.env['keg.keg']._find_by_serial(serial)
        if not keg:
            return {'warning': {'title': _("Unknown keg"), 'message': _("No keg with serial “%s”.", serial)}}
        if keg in self.keg_ids:
            return {'warning': {'title': _("Already scanned"), 'message': _("Keg %s is already loaded.", keg.name)}}
        if keg.state != 'filled':
            return {'warning': {'title': _("Keg not ready"), 'message': _(
                "Keg %(serial)s is %(state)s: only filled kegs can be delivered.",
                serial=keg.name, state=keg._state_label(keg.state))}}
        # The onchange snapshot does not carry the moves' sale lines: read the saved delivery.
        keg_moves = self._origin._get_keg_moves()
        if keg.product_id not in keg_moves.product_id:
            return {'warning': {'title': _("Not on this delivery"), 'message': _(
                "Keg %(serial)s contains %(beer)s, which is not on this delivery.",
                serial=keg.name, beer=keg.product_id.display_name)}}
        demand = sum(
            m.product_uom._compute_quantity(m.product_uom_qty, m.product_id.uom_id)
            for m in keg_moves if m.product_id == keg.product_id)
        if len(self.keg_ids.filtered(lambda k: k.product_id == keg.product_id)) >= round(demand):
            return {'warning': {'title': _("Quantity reached"), 'message': _(
                "All the %s kegs of this delivery are already loaded.", keg.product_id.display_name)}}
        self.keg_ids |= keg

    def _prepare_keg_dispatch(self):
        """Check the kegs loaded against the quantities being delivered.

        :return: list of (kegs, stock move) to dispatch once the moves are done
        """
        plan = []
        for picking in self.filtered(lambda p: p.picking_type_code == 'outgoing'):
            moves = picking._get_keg_moves()
            if not moves and not picking.keg_ids:
                continue
            # Moves not picked are not delivered now: they go to the backorder.
            done_by_product = defaultdict(float)
            for move in moves.filtered('picked'):
                done_by_product[move.product_id] += move.product_uom._compute_quantity(
                    move.quantity, move.product_id.uom_id)
            not_filled = picking.keg_ids.filtered(lambda k: k.state != 'filled')
            if not_filled:
                raise UserError(_("These kegs are not filled and cannot leave the brewery: %s",
                                  ", ".join(not_filled.mapped('name'))))
            errors = []
            for product in moves.product_id | picking.keg_ids.product_id:
                expected = round(done_by_product.get(product, 0.0))
                loaded = picking.keg_ids.filtered(lambda k: k.product_id == product)
                if len(loaded) != expected:
                    errors.append(_("• %(beer)s: %(expected)s delivered, %(loaded)s kegs scanned",
                                    beer=product.display_name, expected=expected, loaded=len(loaded)))
                    continue
                for move in moves.filtered(lambda m: m.product_id == product and m.picked):
                    qty = round(move.product_uom._compute_quantity(move.quantity, product.uom_id))
                    if qty:
                        plan.append((loaded[:qty], move))
                        loaded = loaded[qty:]
            if errors:
                raise UserError(_(
                    "%(picking)s: scan the kegs loaded on the truck before validating the delivery "
                    "(Kegs tab).\n\n%(errors)s",
                    picking=picking.name, errors="\n".join(errors)))
        return plan

    def _action_done(self):
        plan = self._prepare_keg_dispatch()
        res = super()._action_done()
        for kegs, move in plan:
            # Warehouse users validate deliveries; keg custody follows the validated delivery.
            kegs.sudo()._dispatch(move.sale_line_id, picking_id=move.picking_id.id)
        return res
