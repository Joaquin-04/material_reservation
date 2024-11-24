from odoo import api, fields, models, _ , Command
import logging

_logger = logging.getLogger(__name__)

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    material_reservation_ids = fields.One2many(
        'sale.order.material.reservation.line', 'picking_id', string='Material Reservations'
    )

    sale_stock_link_id = fields.Many2one('sale.stock.link', string='Sale Stock Link')
    
    has_reservation = fields.Boolean(string='Tiene una Reserva')

    def _compute_has_reservation(self):
        for picking in self:
            picking.has_reservation = bool(picking.material_reservation_ids)
            
    def button_validate(self):
        for move in self.move_ids_without_package:
            if not move.sale_line_id:
                # Si no hay una línea de venta asociada, asegurarse de no afectar líneas de venta
                move.sale_line_id = False  # Por redundancia, para que Odoo no lo calcule en cascada
        return super(StockPicking, self).button_validate()


         

class StockMove(models.Model):
    _inherit = "stock.move"

    sale_stock_link_id = fields.Many2one('sale.stock.link', string='Sale Stock Link')
    
    reservation_line_id = fields.Many2one('sale.order.material.reservation.line', 'Reservation Line')
    
    def _action_done(self, cancel_backorder=False):
        for move in self:
            # Si hay una línea de reserva, realiza las actualizaciones
            if move.reservation_line_id:
                move.reservation_line_id.qty_done += move.quantity or 0
                _logger.warning(f"Cantidad hechas {move.quantity} - {move.reservation_line_id.qty_done}")
            else:
                _logger.warning(f"El movimiento {move.id} no está relacionado con ninguna línea de reserva.")
        
        # Llama al método original para completar la operación
        return super(StockMove, self)._action_done(cancel_backorder=cancel_backorder)


    @api.model
    def create(self, vals):
        # Si 'reservation_line_id' no está presente, no se fuerza su asignación
        vals['quantity'] = 0.0    # Cantidad hecha
        record = super().create(vals)

        record['quantity']=0.0
        _logger.warning(f"Creando StockMove\nRecord: {record}\nValores: {vals}")
        return record
