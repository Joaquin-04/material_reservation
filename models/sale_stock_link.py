from odoo import models, fields, api

class SaleStockLink(models.Model):
    """Modelo que me permite asociar una venta con una transaccion y una reserva"""
    _name = 'sale.stock.link'
    _description = 'Sale Stock Link'

    name = fields.Char(string="Reference", required=True, copy=False, default='New')
    sale_order_id = fields.Many2one('sale.order', string="Sale Order", ondelete="cascade")
    picking_ids = fields.One2many('stock.picking', 'sale_stock_link_id', string="Pickings")
    move_ids = fields.One2many('stock.move', 'sale_stock_link_id', string="Stock Moves")
    company_id = fields.Many2one('res.company', string="Company", required=True, default=lambda self: self.env.company)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('sale.stock.link') or 'New'
        return super(SaleStockLink, self).create(vals)
