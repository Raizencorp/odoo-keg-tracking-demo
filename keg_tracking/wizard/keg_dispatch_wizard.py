from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError


class KegDispatchWizard(models.TransientModel):
    _name = 'keg.dispatch.wizard'
    _description = 'Dispatch Kegs on a Sales Order'

    sale_order_id = fields.Many2one('sale.order', required=True, readonly=True)
    partner_shipping_id = fields.Many2one(related='sale_order_id.partner_shipping_id', string='Deliver To')
    scan = fields.Char(string='Scan Serial', help="Scan or type a keg serial number and press Enter.")
    line_ids = fields.One2many('keg.dispatch.wizard.line', 'wizard_id', string='Kegs to Dispatch')

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        order = self.env['sale.order'].browse(res.get('sale_order_id'))
        if order and 'line_ids' in fields_list:
            res['line_ids'] = [
                Command.create({
                    'sale_line_id': line.id,
                    'qty_remaining': line._get_keg_remaining(),
                })
                for line in order.order_line
                if line.keg_type_id and line._get_keg_remaining() > 0
            ]
        return res

    @api.onchange('scan')
    def _onchange_scan(self):
        if not self.scan:
            return
        serial, self.scan = self.scan, False
        keg = self.env['keg.keg']._find_by_serial(serial)
        if not keg:
            return {'warning': {'title': _("Unknown keg"), 'message': _("No keg with serial “%s”.", serial)}}
        if keg in self.line_ids.keg_ids:
            return {'warning': {'title': _("Already scanned"), 'message': _("Keg %s is already on this delivery.", keg.name)}}
        if keg.state != 'filled':
            return {'warning': {'title': _("Keg not ready"), 'message': _(
                "Keg %(serial)s is %(state)s: only filled kegs can be dispatched.",
                serial=keg.name, state=keg._state_label(keg.state))}}
        candidates = self.line_ids.filtered(lambda l: l.product_id == keg.product_id)
        if not candidates:
            return {'warning': {'title': _("Not on this order"), 'message': _(
                "Keg %(serial)s contains %(beer)s, which is not left to dispatch on this order.",
                serial=keg.name, beer=keg.product_id.display_name)}}
        line = candidates.filtered(lambda l: len(l.keg_ids) < l.qty_remaining)[:1]
        if not line:
            return {'warning': {'title': _("Quantity reached"), 'message': _(
                "All the %s kegs of this order have already been scanned.", keg.product_id.display_name)}}
        line.keg_ids |= keg

    def _check_can_dispatch(self):
        """Hook: extended when kegs must be dispatched from another document (delivery orders)."""

    def action_confirm(self):
        self.ensure_one()
        kegs = self.line_ids.keg_ids
        if not kegs:
            raise UserError(_("Scan or select the kegs loaded on the truck."))
        if len(kegs) != sum(len(line.keg_ids) for line in self.line_ids):
            raise UserError(_("The same keg was selected on several lines."))
        for line in self.line_ids:
            sale_line = line.sale_line_id
            if sale_line.order_id != self.sale_order_id:
                raise UserError(_("This line does not belong to %s.", self.sale_order_id.name))
            # Recomputed from the order: never trust the quantity displayed in the dialog.
            remaining = sale_line._get_keg_remaining()
            if len(line.keg_ids) > remaining:
                raise UserError(_(
                    "%(selected)s kegs of %(beer)s selected but only %(remaining)s left to dispatch.",
                    selected=len(line.keg_ids), beer=line.product_id.display_name, remaining=remaining))
        self._check_can_dispatch()
        for line in self.line_ids.filtered('keg_ids'):
            line.keg_ids._dispatch(line.sale_line_id)
        order = self.sale_order_id
        order.sudo().message_post(body=_("Kegs dispatched to %(partner)s: %(serials)s",
                                  partner=order.partner_shipping_id.display_name,
                                  serials=", ".join(kegs.sorted('name').mapped('name'))))
        return self.env['keg.keg']._action_done(_("%(count)s keg(s) dispatched on %(order)s.",
                                                  count=len(kegs), order=order.name))


class KegDispatchWizardLine(models.TransientModel):
    _name = 'keg.dispatch.wizard.line'
    _description = 'Dispatch Kegs Line'

    wizard_id = fields.Many2one('keg.dispatch.wizard', required=True, ondelete='cascade')
    sale_line_id = fields.Many2one('sale.order.line', required=True)
    product_id = fields.Many2one(related='sale_line_id.product_id', string='Beer')
    keg_type_id = fields.Many2one(related='sale_line_id.keg_type_id')
    qty_remaining = fields.Integer(string='To Dispatch')
    keg_ids = fields.Many2many(
        'keg.keg', string='Kegs', domain="[('state', '=', 'filled'), ('product_id', '=', product_id)]")
    keg_count = fields.Integer(compute='_compute_keg_count', string='Scanned')

    @api.depends('keg_ids')
    def _compute_keg_count(self):
        for line in self:
            line.keg_count = len(line.keg_ids)
