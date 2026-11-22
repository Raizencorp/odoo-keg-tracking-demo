from odoo import _, api, fields, models
from odoo.exceptions import UserError


class KegLostWizard(models.TransientModel):
    _name = 'keg.lost.wizard'
    _description = 'Declare Kegs Lost'

    keg_ids = fields.Many2many('keg.keg', string='Kegs', domain="[('state', '=', 'at_customer')]")
    charge_customer = fields.Boolean(
        default=True,
        help="Prepare a draft invoice charging each customer the replacement value of its lost "
             "kegs minus the deposit already retained.")
    reason = fields.Char(required=True, help="E.g. customer unreachable, establishment closed, keg reported stolen.")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    charge_total = fields.Monetary(compute='_compute_charge_total', string='Amount to Charge')

    @api.depends('keg_ids', 'charge_customer')
    def _compute_charge_total(self):
        for wizard in self:
            wizard.charge_total = sum(
                max(keg.type_id.replacement_value - keg.deposit_amount_held, 0.0) for keg in wizard.keg_ids
            ) if wizard.charge_customer else 0.0

    def action_confirm(self):
        self.ensure_one()
        if not self.keg_ids:
            raise UserError(_("Select the kegs to declare lost."))
        count = len(self.keg_ids)
        invoices = self.keg_ids._declare_lost(charge_customer=self.charge_customer, note=self.reason)
        return self.env['keg.keg']._action_done(_("%s keg(s) declared lost.", count), invoices)
