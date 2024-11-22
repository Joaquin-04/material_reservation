import logging

from odoo import api, fields, models, _ , Command
from odoo.exceptions import UserError,ValidationError

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    #fields 
    material_reservation_ids = fields.One2many(
        'sale.order.material.reservation.line', 'order_id', 
        string="Material Reservation"
    )

    studio_almacen = fields.Many2one(
        'stock.warehouse', 
        string="Almacén", 
        default=lambda self: self._get_default_warehouse()
    )

    sale_stock_link_id = fields.Many2one(
        'sale.stock.link', string="Sale Stock Link", ondelete="cascade"
    )

    material_reservation_status = fields.Selection([
        ('pending', "Sin entregar"),
        ('started', "Started"),
        ('partial', "Parcialmente entregado"),
        ('full', "Completamente entregado"),
    ], string="Material Reservation Status", compute="_compute_material_reservation_status")
 
    material_reservation_picking_generated = fields.Boolean(
        string="Material Reservation Picking Generated",
        default=False,
        help="Indica si la reserva de materiales ya se ha generado para evitar duplicados."
    )

    reservation_count = fields.Integer(
        string='Reservation Count',
        compute='_compute_reservation_count',
        store=True
    )
    
    # Computed Fields    
    @api.depends('sale_stock_link_id.picking_ids')
    def _compute_reservation_count(self):
        for order in self:
            if order.sale_stock_link_id:
                order.reservation_count = len(order.sale_stock_link_id.picking_ids)
            else:
                order.reservation_count = 0


    @api.depends('material_reservation_ids.product_uom_qty', 'picking_ids.state')
    def _compute_material_reservation_status(self):
        """Actualiza el estado de la reserva de materiales en función del estado de las transferencias."""
        for order in self:
            pickings = order.picking_ids
            if not pickings:
                order.material_reservation_status = 'pending'
            elif all(pick.state == 'done' for pick in pickings):
                order.material_reservation_status = 'full'
            elif any(pick.state == 'assigned' for pick in pickings):
                order.material_reservation_status = 'partial'
            elif any(pick.state in ['waiting', 'confirmed'] for pick in pickings):
                order.material_reservation_status = 'started'
            else:
                order.material_reservation_status = 'pending'

    # Default Values

    @api.model
    def _get_default_warehouse(self):
        """Define el almacén por defecto basado en la empresa activa del usuario."""

        company_id = self.env.company.id
        #_logger.warning(f"Compañia actual: ID:{ company_id  } - Nombre: { self.env.company.name }")

        default_warehouses = self.env['stock.warehouse'].search([
            ('company_id', '=', self.env.company.id)
        ])
        "Estoy en NOA"
        if company_id == 2:
            #_logger.warning(f"Almacenes de NOA: { default_warehouses } ")
            #Eligo como almacen predeterminado NOA Aberturas en Cristalizando
            default_warehouse = default_warehouses[1]
        elif company_id == 3:
            default_warehouse = default_warehouses[0]
        else:
            default_warehouse = default_warehouses[0] if default_warehouses else False
            

            
        return default_warehouse.id if default_warehouse else False


    # Actions
    
    def action_view_reservations(self):
        self.ensure_one()
        action = self.env.ref('stock.action_picking_tree_all').read()[0]
        pickings = self.sale_stock_link_id.picking_ids
        action['domain'] = [('id', 'in', pickings.ids)]
        return action

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        # Crear transferencia de reserva de materiales si hay productos
        #if self.material_reservation_ids and not self.material_reservation_picking_generated:


        # Crear o asociar el SaleStockLink
        if not self.sale_stock_link_id:
            self.sale_stock_link_id = self.env['sale.stock.link'].create({
                'sale_order_id': self.id,
                'company_id': self.company_id.id,
            })

        
        if self.material_reservation_ids:
            self.action_create_material_reservation()
        return res


    def action_create_material_reservation(self):
        """Botón para crear manualmente la transferencia de reserva."""
        
        self.ensure_one()
        if not self.material_reservation_ids:
            raise UserError("No hay productos en la reserva de materiales.")
       
        picking = self._create_material_reservation_picking()
        #picking['has_reservation']=1

        # Verificar si ya se generó la reserva de materiales
        #if self.material_reservation_picking_generated:
        #    raise UserError("La reserva de materiales ya ha sido generada para esta orden.")

        # Agregar el picking a picking_ids
        """
        self.write({
            'picking_ids': [(4, picking.id)],
            #'material_reservation_picking_generated': True,
        })
        """

        #_logger.warning(f"Transferencia: {picking} \n Viene de una reserva?: {picking.has_reservation} \nGrupo {self.procurement_group_id} {self.procurement_group_id.id} - {picking.group_id}")
        
        self.delivery_count += 1  # Actualiza el contador de reserva
        
        self._compute_material_reservation_status()  # Recalcula el estado de la reserva


    #helpers
    def _get_picking_type(self):
        """Retrieve the picking type for outgoing shipments based on the selected warehouse."""
        picking_type = self.env['stock.picking.type'].search([
            ('warehouse_id', '=', self.studio_almacen.id),
            ('company_id', '=', self.company_id.id),
            ('code', '=', 'outgoing'),
        ], limit=1)
        if not picking_type:
            raise UserError(_("No existe un tipo de salida para el almacen seleccionado."))
        return picking_type

    def _create_material_reservation_picking(self):

        # Crea la transferencia de salida utilizando el almacén seleccionado
        picking_type = self._get_picking_type()

        # Revisa si se encontró un tipo de picking para el almacén especificado
        if not picking_type:
            raise ValueError("No se encontró un tipo de albarán de salida para el almacén seleccionado.")
        
        
        # Crear el picking (transferencia) con el almacén definido        
        picking = self.env['stock.picking'].create({
            'partner_id': self.partner_id.id,
            'location_id': picking_type.default_location_src_id.id,
            'location_dest_id': self.partner_id.property_stock_customer.id,
            'picking_type_id': picking_type.id,
            'origin': f"{self.name} - Reserva de Materiales",
            'scheduled_date': fields.Datetime.now(),
            'date_deadline': fields.Datetime.now(),
            'company_id': self.company_id.id,
            'move_type': 'direct',
            'state': 'assigned',  # Estado de transferencia como asignada
            'sale_stock_link_id': self.sale_stock_link_id.id,
            'has_reservation': True,  # Identificar como reserva de materiales'
        })


        ##_logger.warning(f"Transferencia: {picking} \nTipo de transferencia: {picking_type}  \n Viene de una reserva?: {picking.has_reservation} \nGrupo {self.procurement_group_id} {self.procurement_group_id.id} - {picking.group_id}")
        
        

        self._add_moves_to_picking(picking,picking_type)
        #picking['has_reservation']=True
        return picking
        # Part of Odoo. See LICENSE file for full copyright and licensing details.

    def _add_moves_to_picking(self,picking,picking_type):
        """Agrega movimientos al picking basado en las líneas de reserva de materiales."""

        """
        # Verificar si existe el procurement_group_id, si no, crearlo
        if not self.procurement_group_id:
            self.procurement_group_id = self.env['procurement.group'].create({
                'name': self.name,
                'sale_id': self.id,
                'partner_id': self.partner_id.id,
            })
        """    

        
        move_ids = []
        # Lógica para agregar líneas a la reserva de materiales
        for line in self.material_reservation_ids:
            # Crea cada movimiento de stock y almacena el ID en la lista
            move = self.env['stock.move'].create({
                'name': line.name or line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.product_uom_qty,
                'product_uom': line.product_uom.id,
                'location_id': picking_type.default_location_src_id.id,
                'location_dest_id': self.partner_id.property_stock_customer.id,
                'picking_id': picking.id,
                'company_id': self.company_id.id,
                'date': fields.Datetime.now(),
                'state': 'assigned',  # Estado de movimiento asignado
                'reservation_line_id': line.id,
                #'group_id': self.procurement_group_id.id,
                'sale_stock_link_id': self.sale_stock_link_id.id,  # Nueva relación
                 # Asegúrate de no establecer el sale_line_id
                'sale_line_id': False,
            })
            # Agrego la relacion de la linea de movimiento con la linea de la reserva
            line.move_ids = move
            # Añadir el ID del movimiento a la lista
            move_ids.append(move.id)
            
        # Asigna los IDs al campo 'move_id_without_package' usando Command.clear y Command.set
        picking['move_ids_without_package'] = [Command.clear(), Command.set(move_ids)]
                

    @api.onchange('material_reservation_ids')
    def _onchange_material_reservation_ids(self):
        #_logger.warning("Iniciando actualización de las cantidades de las líneas en la transferencia.")
        
        # Filtrar solo las transferencias con reservas
        pickings = self.picking_ids.filtered(lambda p: p.has_reservation)
    
        # Verificar si hay transferencias con reservas
        if pickings:
            for picking in pickings:
                #_logger.warning(f"Actualizando picking con ID {picking.id} que tiene reservas.")
                
                # Iterar a través de las líneas de reserva en material_reservation_ids
                for reservation_line in self.material_reservation_ids:
                    # Buscar la línea de stock.move correspondiente en la transferencia
                    matching_move_line = picking.move_ids_without_package.filtered(
                        lambda move: move.reservation_line_id.id == reservation_line._origin.id
                    )
    
                    # Si existe una línea de stock.move que coincide, actualizamos la cantidad
                    if matching_move_line:
                        #_logger.warning(f"Actualizando cantidad en la línea de picking para el producto {reservation_line.product_id.name}\n matching_move_line: {matching_move_line}")

                        # Actualizo la cantidad en la linea correspondiente
                        self.env['stock.move'].browse(matching_move_line._origin.id).product_uom_qty = reservation_line.product_uom_qty
                
                    else:
                        _logger.warning(f"No se encontró una línea en la transferencia que corresponda a la reserva con ID {reservation_line.id}.")
        else:
            _logger.warning("No hay transferencias que tengan reservas.")


    
    


class SaleOrderMaterialReservationLine(models.Model):
    _name = 'sale.order.material.reservation.line'
    _description = 'Sale Order Material Reservation Line'

    name = fields.Text(
    string="Description",
    store=True, readonly=False, required=True,
    compute='_compute_name'
    )

    qty_pending = fields.Float(
        string="Pending Quantity", 
        compute="_compute_qty_pending", 
        store=True
    )

    
    # Nuevo campo para las cantidades realizadas
    qty_done = fields.Float(string="Done Quantity", readonly=True, default=0.0)
    
    picking_id = fields.Many2one('stock.picking', string='Picking')

    move_ids = fields.One2many('stock.move', 'reservation_line_id', string='Stock Moves')
    
    order_id = fields.Many2one('sale.order', string="Order", ondelete="cascade",required=True)
    # Order-related fields
    company_id = fields.Many2one(
        related='order_id.company_id',
        store=True, index=True, precompute=True)
    
    currency_id = fields.Many2one(
        related='order_id.currency_id',
        depends=['order_id.currency_id'],
        store=True, precompute=True)
    
    order_partner_id = fields.Many2one(
        related='order_id.partner_id',
        string="Customer",
        store=True, index=True, precompute=True)
    
    salesman_id = fields.Many2one(
        related='order_id.user_id',
        string="Salesperson",
        store=True, precompute=True)
    
    state = fields.Selection(
        related='order_id.state',
        string="Order Status",
        copy=False, store=True, precompute=True)
    
    tax_country_id = fields.Many2one(related='order_id.tax_country_id')


    # Fields specifying custom line logic
    display_type = fields.Selection(
        selection=[
            ('line_section', "Section"),
            ('line_note', "Note"),
        ],
        default=False)

        
    product_id = fields.Many2one('product.product', string="Product", required=True)
    
    product_uom_qty = fields.Float(string="Quantity", default=1.0, required=True)
    #product_uom_category_id = fields.Many2one(related='product_id.uom_id.category_id', depends=['product_id'])
    
    product_uom = fields.Many2one(
        comodel_name='uom.uom',
        string="Unit of Measure",
        compute='_compute_product_uom',
        store=True, readonly=False, precompute=True, ondelete='restrict')
    
    price_unit = fields.Float(string="Unit Price")
    
    tax_ids = fields.Many2many('account.tax', string="Taxes")
    
    availability = fields.Float(string="Availability", readonly=True)

    
    subtotal = fields.Float(string="Subtotal (w/o taxes)", readonly=True)



    def write(self, vals):
        #_logger.warning(f"Entrando en write de la linea de reserva. Valores: {vals}")
        res = super(SaleOrderMaterialReservationLine, self).write(vals)
        for line in self:
            # Verificar si se está cambiando la cantidad
            if 'product_uom_qty' in vals:
                new_qty = vals['product_uom_qty']
                if new_qty < line.qty_done:
                    raise UserError("No puedes reducir la cantidad por debajo de la cantidad hecha.")

                #_logger.warning(f"linea {line} - {line.picking_id}")
                #_logger.warning(f"Orden de venta {self.order_id}")
                pickings = self.order_id.sale_stock_link_id.picking_ids
                #_logger.warning(f"pickings: {pickings}")
                # Actualizar transacciones relacionadas
                if pickings:
                    for move in pickings.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
                        #_logger.warning(f"movimiento {move}")
                        # Actualizar la demanda si coincide con la línea de reserva
                        if move.reservation_line_id == line:
                            #_logger.warning(f"linea de reserva {move.reservation_line_id} - {line}")
                            remaining_qty = new_qty - line.qty_done
                            move.product_uom_qty = max(0, remaining_qty)
                            
                            # Cancelar movimiento si la demanda es 0
                            if move.product_uom_qty == 0:
                                move.state = 'cancel'

                    # Cancelar la transacción si todas las demandas son 0
                    if all(m.product_uom_qty == 0 for m in line.picking_id.move_ids):
                        line.picking_id.state = 'cancel'
        return res



        """
        # Restricción para que la cantidad no sea menor que qty_done
        @api.constrains('product_uom_qty')
        def _check_qty_done(self):
            for line in self:
                if line.product_uom_qty < line.qty_done:
                    raise ValidationError(
                        _("La cantidad no puede ser menor que la cantidad hecha: (%s).") % line.qty_done
                    )
    
        """
    
    @api.depends('product_uom_qty', 'qty_done')
    def _compute_qty_pending(self):
        for line in self:
            line.qty_pending = max(0, line.product_uom_qty - line.qty_done)

    
    @api.depends('product_id')
    def _compute_product_uom(self):
        for line in self:
            if not line.product_uom or (line.product_id.uom_id.id != line.product_uom.id):
                line.product_uom = line.product_id.uom_id

    @api.depends('order_id','product_id')
    def _compute_name(self):

        for line in self:
            #_logger.warning(f"QComputing Name")
            if line.order_id and line.product_id:
                line.name = f"{line.order_id.name} - {line.product_id.name}"
                #_logger.warning(f"name: {line.name}")
            elif self.order_id:
                line.name = f"{self.order_id}"
            else:
                line.name=""

    @api.depends('price_unit', 'product_uom_qty')
    def _update_subtotal(self):
        for line in self:
            line['subtotal']=line.price_unit * line.product_uom_qty
        

    
