from odoo import _, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    keg_count = fields.Integer(
        string='Kegs Held', compute='_compute_keg_stats', groups='keg_tracking.group_keg_user')
    keg_overdue_count = fields.Integer(
        string='Overdue Kegs', compute='_compute_keg_stats', groups='keg_tracking.group_keg_user')
    keg_deposit_held = fields.Monetary(
        string='Keg Deposits Held', compute='_compute_keg_stats', groups='keg_tracking.group_keg_user',
        currency_field='keg_currency_id')
    keg_currency_id = fields.Many2one(
        'res.currency', compute='_compute_keg_stats', groups='keg_tracking.group_keg_user')

    def _keg_domain(self):
        self.ensure_one()
        return [('partner_id', 'child_of', self.id), ('state', '=', 'at_customer')]

    def _compute_keg_stats(self):
        Keg = self.env['keg.keg']
        for partner in self:
            partner.keg_currency_id = self.env.company.currency_id
            if not partner.id:
                partner.keg_count = partner.keg_overdue_count = 0
                partner.keg_deposit_held = 0.0
                continue
            kegs = Keg.search(partner._keg_domain())
            partner.keg_count = len(kegs)
            partner.keg_overdue_count = len(kegs.filtered('is_overdue'))
            partner.keg_deposit_held = sum(kegs.mapped('deposit_amount_held'))

    def action_view_kegs(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('keg_tracking.action_keg')
        action.update({
            'name': _("Kegs at %s", self.display_name),
            'domain': self._keg_domain(),
            'context': {'create': False},
            'views': [(False, 'list'), (False, 'form')],
            'view_mode': 'list,form',
        })
        return action

    def action_open_keg_return_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Return Kegs"),
            'res_model': 'keg.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_partner_id': self.id},
        }
