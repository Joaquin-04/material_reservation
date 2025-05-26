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

    project_id = fields.Many2one(
        'project.project',
        string="Proyecto",
        domain="[('company_id', 'in', allowed_company_ids)]",
        compute="_compute_project_id",
        readonly=False
    )
    
    def _compute_project_id(self):
        _logger.warning(f"**********************************************COMPUTE**********************************************")
        for picking in self:
            if picking.x_studio_nv_numero_de_obra_relacionada:
                obra_nr = picking.x_studio_nv_numero_de_obra_relacionada
                proyecto = self.env['project.project'].search([('obra_nr','=',obra_nr)])
                picking.project_id = proyecto
                _logger.warning(f"Proyecto {proyecto.name} asignado al remito {picking.name}")
            else:
                _logger.warning(f"No se a asignado asignado nada al remito {picking.name}")
                picking.project_id = False

    def _compute_has_reservation(self):
        for picking in self:
            picking.has_reservation = bool(picking.material_reservation_ids)
            
    def button_validate(self):
        for move in self.move_ids_without_package:
            if not move.sale_line_id:
                # Si no hay una línea de venta asociada, asegurarse de no afectar líneas de venta
                move.sale_line_id = False  # Por redundancia, para que Odoo no lo calcule en cascada
        return super(StockPicking, self).button_validate()


    def write(self, vals):
        _logger.warning("Write!!! Que se activa desde material_reservation stock_picking_extension.py")
        _logger.warning(f"valores: {vals}")
        
        if 'project_id' in vals:
            if vals['project_id']:
                # Se ha asignado un proyecto, obtenemos su información
                project = self.env['project.project'].browse(vals['project_id'])
                if project:
                    
                    new_vals = {}
                    if project.obra_nr:
                        new_vals['x_studio_nv_numero_de_obra_relacionada'] = project.obra_nr
                    else:
                        new_vals['x_studio_nv_numero_de_obra_relacionada'] = False
                    if project.obra_padre_id:
                        new_vals['x_studio_nv_numero_de_obra_padre'] = project.obra_padre_id.obra_nr
                    else:
                        new_vals['x_studio_nv_numero_de_obra_padre'] = project.obra_nr
                    vals.update(new_vals)
            else:
                # Se está borrando el proyecto, establecemos los campos en 0 o False
                vals.update({
                    'x_studio_nv_numero_de_obra_relacionada': 0,
                    'x_studio_nv_numero_de_obra_padre': 0,
                })
        return super(StockPicking, self).write(vals)


         

class StockMove(models.Model):
    _inherit = "stock.move"

    stage_id = fields.Many2one(
        'material.reservation.stage',
        string="Etapa",
        ondelete='set null',
        required=False,
        readonly=True,
        help="Stage associated with the material reservation."
    )

    sale_stock_link_id = fields.Many2one('sale.stock.link', string='Sale Stock Link')
    
    reservation_line_id = fields.Many2one('sale.order.material.reservation.line', 'Reservation Line')
    
    def _action_done(self, cancel_backorder=False):
        _logger.warning(f"Entrando al _action_done de stock.Move")
        _logger.warning(f"contexto {self.env.context}")
        
        """Actualiza las cantidades hechas en las líneas de reserva relacionadas."""
        for move in self:
            if move.origin_returned_move_id:
                _logger.warning(f"El movimiento {move.id} es una devolución de {move.origin_returned_move_id.id}")
                # Actualiza cantidades reservadas o hechas en la línea relacionada
                if move.reservation_line_id:
                    move.reservation_line_id.qty_done -= move.quantity or 0
                    _logger.warning(f"Actualizando la línea de reserva para devolución. Cantidad hecha: {move.reservation_line_id.qty_done}")
            else:
                # Si hay una línea de reserva, realiza las actualizaciones
                if move.reservation_line_id:
                    move.reservation_line_id.qty_done += move.quantity or 0
                    _logger.warning(f"Cantidad hechas {move.quantity} - {move.reservation_line_id.qty_done}")
                else:
                    _logger.warning(f"El movimiento {move.id} no está relacionado con ninguna línea de reserva.")
            
        # Llama al método original para completar la operación
        return super(StockMove, self)._action_done(cancel_backorder=cancel_backorder)


    
    def create(self, vals):
        _logger.warning(f"Entrando al create de Stock.Move\n valores {type(vals) == 'dict'}")

        if type(vals) == 'dict':
            if 'is_inventory'in vals and not vals[0]['is_inventory']:
                _logger.warning(f"Entre, verifico si esta relacionada con una reserva")
                # Si se proporciona una línea de reserva, hereda la etapa automáticamente.
                if 'reservation_line_id' in vals and vals['reservation_line_id']:
                    reservation_line = self.env['sale.order.material.reservation.line'].browse(vals['reservation_line_id'])
                    vals['stage_id'] = reservation_line.stage_id.id
        
                # Si hay un vínculo con SaleStockLink, pero sin línea de reserva, se verifica si es aplicable asignar una etapa.
                elif 'sale_stock_link_id' in vals and vals['sale_stock_link_id']:
                    sale_stock_link = self.env['sale.stock.link'].browse(vals['sale_stock_link_id'])
                    _logger.warning(f"Tengo sale_stock_link: {sale_stock_link}")
                    if sale_stock_link.sale_order_id:
                        # Busca la línea de reserva asociada para este movimiento específico
                        reservations = sale_stock_link.sale_order_id.mapped('material_reservation_ids')
                        _logger.warning(f" reservations: {reservations}")
                        product_id = vals.get('product_id')
                        _logger.warning(f" product_id: {product_id}")
                        specific_reservations = reservations.filtered(lambda r: r.product_id.id == product_id)
                        _logger.warning(f" specific_reservations: {specific_reservations}")
                        if specific_reservations:
                            vals['stage_id'] = specific_reservations[0].stage_id.id
                            _logger.warning(f"Heredando etapa de la reserva específica para producto {product_id}: {specific_reservations[0].stage_id}")
        
                
                # Si 'reservation_line_id' no está presente, no se fuerza su asignación
                vals['quantity'] = 0.0    # Cantidad hecha
                record = super().create(vals)
        
                record['quantity']=0.0
                _logger.warning(f"StockMove creado con ID {record.id}, Stage: {record.stage_id}, Reservation Line: {record.reservation_line_id}")
                return record
            else:
                _logger.warning(f"Lo mandamos al create del super")
                return super().create(vals)
        else:
            _logger.warning(f"Lo mandamos al create del super")
            return super().create(vals)
    

    def write(self, vals):
        _logger.warning(f"Entrando en el write valores: {vals}")
        _logger.warning(f"valores: {vals}")
        # Actualiza la etapa si la línea de reserva cambia.
        if 'reservation_line_id' in vals and vals['reservation_line_id']:
            reservation_line = self.env['sale.order.material.reservation.line'].browse(vals['reservation_line_id'])
            vals['stage_id'] = reservation_line.stage_id.id
        return super(StockMove,self).write(vals)




