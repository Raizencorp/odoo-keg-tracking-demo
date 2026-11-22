from odoo import fields, models


class KegMovement(models.Model):
    _inherit = 'keg.movement'

    picking_id = fields.Many2one('stock.picking', string='Delivery', index='btree_not_null')
