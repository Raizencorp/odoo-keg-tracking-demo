from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class KegType(models.Model):
    _name = 'keg.type'
    _description = 'Keg Type'
    _order = 'sequence, capacity, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    capacity = fields.Float(string='Capacity (L)', required=True, digits=(16, 1))
    deposit_amount = fields.Monetary(
        string='Deposit', required=True,
        help="Amount charged to the customer for each keg dispatched and refunded when it comes back.")
    replacement_value = fields.Monetary(
        required=True,
        help="Cost of replacing the keg. A customer who loses a keg is charged this value "
             "minus the deposit already retained.")
    max_days_at_customer = fields.Integer(
        string='Rotation Target (days)', required=True, default=60,
        help="A keg held by a customer longer than this is flagged as overdue and the "
             "salesperson receives a reminder.")
    deposit_product_id = fields.Many2one(
        'product.product', string='Deposit Product', required=True, check_company=True,
        domain="[('type', '=', 'service')]",
        help="Product used for deposit lines on sales orders and deposit refunds on credit notes.")
    loss_product_id = fields.Many2one(
        'product.product', string='Lost Keg Product', required=True, check_company=True,
        domain="[('type', '=', 'service')]",
        help="Product used to invoice customers for kegs declared lost.")
    keg_ids = fields.One2many('keg.keg', 'type_id', string='Kegs')
    keg_count = fields.Integer(compute='_compute_keg_stats', string='Fleet')
    keg_at_customer_count = fields.Integer(compute='_compute_keg_stats', string='At Customers')
    keg_overdue_count = fields.Integer(compute='_compute_keg_stats', string='Overdue')

    _sql_constraints = [
        ('capacity_positive', 'CHECK(capacity > 0)', "The keg capacity must be positive."),
        ('rotation_positive', 'CHECK(max_days_at_customer > 0)', "The rotation target must be at least one day."),
    ]

    @api.constrains('deposit_amount', 'replacement_value')
    def _check_amounts(self):
        for keg_type in self:
            if keg_type.deposit_amount < 0:
                raise ValidationError(_("The deposit of keg type “%s” cannot be negative.", keg_type.name))
            if keg_type.replacement_value < keg_type.deposit_amount:
                raise ValidationError(_(
                    "The replacement value of keg type “%s” must be at least its deposit: "
                    "a lost keg is charged the replacement value minus the deposit retained.",
                    keg_type.name))

    def _compute_keg_stats(self):
        Keg = self.env['keg.keg']
        fleet = dict(Keg._read_group(
            [('type_id', 'in', self.ids), ('state', '!=', 'retired')], ['type_id'], ['__count']))
        out = dict(Keg._read_group(
            [('type_id', 'in', self.ids), ('state', '=', 'at_customer')], ['type_id'], ['__count']))
        overdue = dict(Keg._read_group(
            [('type_id', 'in', self.ids), ('is_overdue', '=', True)], ['type_id'], ['__count']))
        for keg_type in self:
            keg_type.keg_count = fleet.get(keg_type, 0)
            keg_type.keg_at_customer_count = out.get(keg_type, 0)
            keg_type.keg_overdue_count = overdue.get(keg_type, 0)

    def _action_view_kegs(self, domain, context=None):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('keg_tracking.action_keg')
        action['domain'] = [('type_id', '=', self.id)] + domain
        action['context'] = dict(context or {}, default_type_id=self.id)
        return action

    def action_view_fleet(self):
        return self._action_view_kegs([('state', '!=', 'retired')])

    def action_view_at_customer(self):
        return self._action_view_kegs([('state', '=', 'at_customer')], {'group_by': 'partner_id'})

    def action_view_overdue(self):
        return self._action_view_kegs([('is_overdue', '=', True)], {'group_by': 'partner_id'})
