from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KegReturnWizard(models.TransientModel):
    _name = 'keg.return.wizard'
    _description = 'Register Keg Returns'

    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    scan = fields.Char(string='Scan Serial', help="Scan or type a keg serial number and press Enter.")
    keg_ids = fields.Many2many(
        'keg.keg', string='Returned Kegs',
        domain="[('state', '=', 'at_customer'), ('partner_id', 'child_of', partner_id)]")
    refund_deposit = fields.Boolean(
        string='Refund Deposits', default=True,
        help="Prepare a draft credit note refunding the deposit held for each returned keg.")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    deposit_total = fields.Monetary(compute='_compute_deposit_total', string='Deposit to Refund')
    held_count = fields.Integer(compute='_compute_held_count', string='Kegs Held by Customer')

    @api.depends('keg_ids', 'refund_deposit')
    def _compute_deposit_total(self):
        for wizard in self:
            wizard.deposit_total = sum(wizard.keg_ids.mapped('deposit_amount_held')) if wizard.refund_deposit else 0.0

    @api.depends('partner_id')
    def _compute_held_count(self):
        for wizard in self:
            wizard.held_count = self.env['keg.keg'].search_count(
                [('state', '=', 'at_customer'), ('partner_id', 'child_of', wizard.partner_id.id)]
            ) if wizard.partner_id else 0

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        self.keg_ids = self.keg_ids.filtered(
            lambda k: k.partner_id.commercial_partner_id == self.partner_id.commercial_partner_id)

    @api.onchange('scan')
    def _onchange_scan(self):
        if not self.scan:
            return
        serial, self.scan = self.scan, False
        keg = self.env['keg.keg']._find_by_serial(serial)
        if not keg:
            return {'warning': {'title': _("Unknown keg"), 'message': _("No keg with serial “%s”.", serial)}}
        if keg.state != 'at_customer':
            return {'warning': {'title': _("Keg not at a customer"), 'message': _(
                "Keg %(serial)s is %(state)s, it cannot be returned by a customer.",
                serial=keg.name, state=keg._state_label(keg.state))}}
        customer = keg.partner_id.commercial_partner_id
        if not self.partner_id:
            self.partner_id = customer
        elif customer != self.partner_id.commercial_partner_id:
            return {'warning': {'title': _("Keg registered at another customer"), 'message': _(
                "Keg %(serial)s is registered at %(holder)s. Register its return from that customer.",
                serial=keg.name, holder=keg.partner_id.display_name)}}
        self.keg_ids |= keg

    def action_confirm(self):
        self.ensure_one()
        if not self.keg_ids:
            raise UserError(_("Scan or select the kegs collected from the customer."))
        foreign = self.keg_ids.filtered(
            lambda k: k.partner_id.commercial_partner_id != self.partner_id.commercial_partner_id)
        if foreign:
            raise UserError(_("These kegs are not registered at %(customer)s: %(serials)s",
                              customer=self.partner_id.display_name,
                              serials=", ".join(foreign.mapped('name'))))
        count = len(self.keg_ids)
        refunds = self.keg_ids._register_return(refund_deposit=self.refund_deposit)
        return self.env['keg.keg']._action_done(
            _("%(count)s keg(s) returned by %(customer)s.", count=count, customer=self.partner_id.display_name),
            refunds)
