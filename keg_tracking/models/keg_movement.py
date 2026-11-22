from odoo import fields, models

MOVEMENT_TYPES = [
    ('fill', 'Filled'),
    ('dispatch', 'Dispatched'),
    ('return', 'Returned'),
    ('clean', 'Cleaned'),
    ('maintenance', 'Sent to Maintenance'),
    ('repaired', 'Back in Service'),
    ('lost', 'Declared Lost'),
    ('recovered', 'Recovered'),
    ('retire', 'Retired'),
]


class KegMovement(models.Model):
    """Append-only custody log. Records are only created by the keg workflow methods."""
    _name = 'keg.movement'
    _description = 'Keg Movement'
    _order = 'date desc, id desc'
    _rec_name = 'keg_id'

    keg_id = fields.Many2one('keg.keg', string='Keg', required=True, index=True, ondelete='cascade')
    type_id = fields.Many2one(related='keg_id.type_id', store=True, string='Keg Type')
    company_id = fields.Many2one(related='keg_id.company_id', store=True, index=True)
    movement_type = fields.Selection(MOVEMENT_TYPES, string='Operation', required=True)
    date = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    user_id = fields.Many2one('res.users', string='Done By', default=lambda self: self.env.user)
    partner_id = fields.Many2one('res.partner', string='Customer', index=True)
    product_id = fields.Many2one('product.product', string='Beer')
    sale_order_id = fields.Many2one('sale.order', string='Sales Order', index=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Order Line', index=True)
    move_id = fields.Many2one('account.move', string='Invoice / Credit Note')
    note = fields.Char()
