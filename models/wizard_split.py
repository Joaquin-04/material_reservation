from odoo import models, fields, api
from odoo.exceptions import UserError

class MaterialReservationSplit(models.TransientModel):
    _name = 'material.reservation.split.wizard'
    _description = 'Wizard para dividir línea de reserva'

    line_id = fields.Many2one(
        'sale.order.material.reservation.line', string='Línea', required=True
    )

    project_id = fields.Many2one(
        'project.project',
        string='Proyecto',
        default=lambda self: self.env.context.get('default_project_id'),
        readonly=True,
    )

    

    
    split_lines = fields.One2many(
        'material.reservation.split.line', 'wizard_id', string='Repartos'
    )

    
    def action_confirm(self):
        self.ensure_one()
        total = sum(self.split_lines.mapped('quantity'))
        if total > self.line_id.qty_pending or total <= 0:
            raise UserError(f'No puedes repartir más que la cantidad pendiente. {self.line_id.qty_pending} ni menor o igual a 0.')
        self.line_id.product_uom_qty -= total
        for rec in self.split_lines:
            self.env['sale.order.material.reservation.line'].create({
                'order_id': self.line_id.order_id.id,
                'product_id': self.line_id.product_id.id,
                'product_uom_qty': rec.quantity,
                'stage_id': rec.stage_id.id,
                'price_unit': self.line_id.price_unit,
            })
        return {'type': 'ir.actions.client', 'tag': 'reload'}

class MaterialReservationSplitLine(models.TransientModel):
    _name = 'material.reservation.split.line'
    _description = 'Lineas del Wizard Split'
    

    wizard_id = fields.Many2one(
        'material.reservation.split.wizard', ondelete='cascade'
    )
    
    stage_id = fields.Many2one(
        'material.reservation.stage',
        string='Etapa',
        required=True,
    )
    #domain="[('project_id','=', wizard_id.line_id.order_id.project_id)]"
    quantity = fields.Float(string='Cantidad', required=True,default=1)


