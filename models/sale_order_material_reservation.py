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

        # Crea la transferencia de salida utilizando el almacén seleccionado
        picking_type = self._get_picking_type()

        # Revisa si se encontró un tipo de picking para el almacén especificado
        if not picking_type:
            raise ValueError("No se encontró un tipo de albarán de salida para el almacén seleccionado.")

        self._add_moves_to_picking(picking,picking_type)

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
        
        #picking['has_reservation']=True
        return picking
        # Part of Odoo. See LICENSE file for full copyright and licensing details.

    def _add_moves_to_picking(self,picking,picking_type):
        """Agrega movimientos al picking basado en las líneas de reserva de materiales."""
        
        move_ids = []
        # Lógica para agregar líneas a la reserva de materiales
        for line in self.material_reservation_ids:
            # Crea cada movimiento de stock y almacena el ID en la lista
            move = self.env['stock.move'].create({
                'name': line.name or line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty_pending,
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
                

    




class SaleOrderMaterialReservationLine(models.Model):
    _name = 'sale.order.material.reservation.line'
    _description = 'Sale Order Material Reservation Line'

    # Campos principales
    name = fields.Text(
        string="Description",
        compute='_compute_name',
        store=True
    )
    qty_pending = fields.Float(
        string="Pending Quantity", 
        compute="_compute_qty_pending", 
        store=True
    )
    qty_done = fields.Float(
        string="Done Quantity", 
        readonly=True, 
        default=0.0
    )
    picking_id = fields.Many2one(
        'stock.picking', 
        string='Picking'
    )
    move_ids = fields.One2many(
        'stock.move', 
        'reservation_line_id', 
        string='Stock Moves'
    )
    order_id = fields.Many2one(
        'sale.order', 
        string="Order", 
        ondelete="cascade", 
        required=True
    )
    product_id = fields.Many2one(
        'product.product', 
        string="Product", 
        required=True
    )
    product_uom_qty = fields.Float(
        string="Quantity", 
        default=1.0, 
        required=True
    )
    
    product_uom = fields.Many2one(
        comodel_name='uom.uom',
        string="Unit of Measure",
        compute='_compute_product_uom',
        store=True,
        readonly=False
    )
    
    price_unit = fields.Float(
        string="Unit Price"
    )
    
    subtotal = fields.Float(
        string="Subtotal (w/o taxes)", 
        compute='_compute_subtotal', 
        store=True
    )

    availability = fields.Float(string="Availability", readonly=True)

    # Related fields
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)

    @api.model
    def create(self, vals):
        record = super().create(vals)
        _logger.info(f"Creando línea de reserva: {record.name} con datos: {vals}")
        record._compute_qty_pending()
        if record.order_id.state == 'sale' and record.qty_pending > 0:
            self._handle_material_reservation([record])
        return record

    @api.model
    def unlink(self):
        for line in self:
            if line.move_ids.filtered(lambda m: m.state not in ("done", "cancel")):
                raise UserError(_("No se puede eliminar esta línea ya que está asociada con una transacción."))
        return super().unlink()

    @api.model
    def write(self, vals):
        res = super().write(vals)
        updated_lines = []
        for line in self:
            if 'product_uom_qty' in vals:
                if vals['product_uom_qty'] < line.qty_done:
                    raise UserError(_("No puedes establecer una cantidad menor a la hecha."))
                line.qty_pending = max(0, vals['product_uom_qty'] - line.qty_done)
                updated_lines.append(line)

        if updated_lines:
            self._handle_material_reservation(updated_lines)
        return res

    @api.depends('product_uom_qty', 'qty_done')
    def _compute_qty_pending(self):
        for line in self:
            line.qty_pending = max(0, line.product_uom_qty - line.qty_done)

    @api.depends('product_id')
    def _compute_product_uom(self):
        for line in self:
            line.product_uom = line.product_id.uom_id

    @api.depends('order_id', 'product_id')
    def _compute_name(self):
        for line in self:
            if line.order_id and line.product_id:
                line.name = f"{line.order_id.name} - {line.product_id.name}"
            elif line.order_id:
                line.name = f"{line.order_id.name} - No Product"
            elif line.product_id:
                line.name = f"No Order - {line.product_id.name}"
            else:
                line.name = "No Description"

    @api.depends('price_unit', 'product_uom_qty')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.price_unit * line.product_uom_qty

    def _handle_material_reservation(self, lines):
        """Handle creation or update of material reservations for multiple lines."""
        # Obtener las órdenes asociadas a las líneas.
        orders = {line.order_id for line in lines}
    
        for order in orders:
            # Filtrar pickings existentes que puedan ser reutilizados.
            pickings = order.sale_stock_link_id.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
            )
    
            reusable_picking = pickings[:1]  # Tomar el primero válido si existe.
            lines_with_pending_qty = [line for line in lines if line.qty_pending > 0]
    
            if reusable_picking:
                # Actualizar o agregar movimientos a un picking existente.
                for line in lines_with_pending_qty:
                    self._add_or_update_moves_in_picking(line, reusable_picking)
                    if reusable_picking.state == "draft":
                        reusable_picking.action_confirm()
                _logger.info(f"Movimientos actualizados o agregados al picking existente {reusable_picking.id}.")
            else:
                # Crear un nuevo picking y asignar movimientos.
                new_picking = self._create_new_picking_for_lines(order, lines_with_pending_qty)
                new_picking.action_confirm()
                _logger.info(f"Nuevo picking creado con ID {new_picking.id} para las líneas: {lines_with_pending_qty}.")


    def _add_or_update_moves_in_picking(self, line, picking):
        """Add or update stock moves in an existing picking."""
        existing_moves = picking.move_ids_without_package.filtered(
            lambda m: m.reservation_line_id == line and m.state not in ('done', 'cancel')
        )
        if existing_moves:
            for move in existing_moves:
                move.product_uom_qty = max(0, line.qty_pending)
                if move.product_uom_qty == 0:
                    move.state = 'cancel'
            _logger.info(f"Movimientos actualizados en el picking {picking.id} para la línea {line.name}")
        elif line.qty_pending > 0:
            # Reactivar o agregar un nuevo movimiento
            new_move = self.env['stock.move'].create({
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty_pending,
                'product_uom': line.product_uom.id,
                'location_id': picking.picking_type_id.default_location_src_id.id,
                'location_dest_id': picking.location_dest_id.id,
                'picking_id': picking.id,
                'company_id': line.company_id.id,
                'reservation_line_id': line.id,
            })
            _logger.info(f"Nuevo movimiento creado en el picking {picking.id} para la línea {line.name}: {new_move}")

    def _create_new_material_reservation(self, line):
        """Create a new picking for the material reservation."""
        sale_order = line.order_id
        if hasattr(sale_order, '_create_material_reservation_picking'):
            new_picking = sale_order._create_material_reservation_picking()
            new_move = self.env['stock.move'].create({
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty_pending,
                'product_uom': line.product_uom.id,
                'location_id': new_picking.picking_type_id.default_location_src_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'picking_id': new_picking.id,
                'company_id': line.company_id.id,
                'reservation_line_id': line.id,
            })
            _logger.info(f"Nuevo picking creado (ID {new_picking.id}) con movimiento {new_move.id} para la línea {line.name}")


    def _create_new_picking_for_lines(self, order, lines):
        """Create a new picking for a set of lines with pending quantities."""
        new_picking = order._create_material_reservation_picking()
    
        for line in lines:
            self.env['stock.move'].create({
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty_pending,
                'product_uom': line.product_uom.id,
                'location_id': new_picking.picking_type_id.default_location_src_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'picking_id': new_picking.id,
                'company_id': line.company_id.id,
                'reservation_line_id': line.id,
            })
        return new_picking




