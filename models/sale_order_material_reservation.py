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

    @api.onchange('x_studio_nv_numero_de_obra_relacionada')
    def _onchange_project_number(self):
        _logger.warning("Entre al onchange de obra_relacionada")
        for reservation in self.material_reservation_ids:
            reservation.stage_id = False  # Vacía la etapa cuando cambia el número de proyecto
    
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
            default_warehouse = self.studio_almacen if self.studio_almacen else False
            

            
        return default_warehouse.id if default_warehouse else False

    
    def write(self, vals):
        # 1) ¿Cambia el proyecto?
        cambiando_proyecto = 'project_id' in vals
        proyecto_nuevo = vals.get('project_id')

        # Primero aplicamos el write estándar
        res = super().write(vals)

        if cambiando_proyecto:
            Stage = self.env['material.reservation.stage']
            for order in self:
                # 2) Si quita el proyecto, limpio etapas
                if not proyecto_nuevo:
                    order.material_reservation_ids.write({'stage_id': False})
                    #_logger.info(f"[Reserva] Cotización {order.name}: proyecto eliminado, limpio etapas.")
                    continue

                # 3) Si asigna proyecto, migramos etapas antiguas al nuevo
                for line in order.material_reservation_ids:
                    proyecto_nuevo = self.env['project.project'].browse(vals['project_id'])
                    etapa_antigua = line.stage_id
                    if not etapa_antigua:
                        continue
                    # Buscar etapa igual en el nuevo proyecto
                    etapa = Stage.search([
                        ('project_number','=', proyecto_nuevo.obra_nr),
                        ('name','=', etapa_antigua.name)], limit=1)
                    if not etapa:
                        etapa = Stage.create({
                            'name':          etapa_antigua.name,
                            'project_number':    proyecto_nuevo.obra_nr,
                        })
                        #_logger.info(f"[Reserva] Creada etapa “{etapa.name}” ({etapa.id}) en proyecto {proyecto_nuevo}")
                    else:
                        _logger.info(f"[Reserva] Reuso etapa “{etapa.name}” ({etapa.id}) en proyecto {proyecto_nuevo}")
                    line.stage_id = etapa.id

        return res


    def write(self, vals):
        """
        Al sobrescribir write:
         1) Detectamos si cambia project_id.
         2) Llamamos al write base una sola vez.
         3) Si se quita el proyecto: limpiamos todas las etapas de reserva.
         4) Si se asigna un proyecto: migramos/reutilizamos etapas antiguas,
            actualizamos campos relacionados y distribución analítica.
        """
        cambiando_proyecto = 'project_id' in vals
        proyecto_id_nuevo = vals.get('project_id')  # puede ser False o int

        #_logger.info(f"[Write] SaleOrder {self.ids}: valores entrantes {vals}")

        # 1) Aplicamos el write estándar
        result = super().write(vals)
        #_logger.debug(f"[Write] SaleOrder {self.ids}: write estándar aplicado")

        if cambiando_proyecto:
            Stage = self.env['material.reservation.stage']
            for order in self:
                # 2) Se quita el proyecto
                if not proyecto_id_nuevo:
                    order.material_reservation_ids.write({'stage_id': False})
                    #_logger.info(f"[Reserva] Order {order.name}: proyecto eliminado, etapas reseteadas")
                    # Limpiar campos de obra relacionada
                    super(SaleOrder, order).write({
                        'x_studio_nv_numero_de_obra_relacionada': 0,
                        'x_studio_nv_numero_de_obra_padre': 0,
                    })
                    # Limpiar distribución analítica
                    order._update_analytic_distribution(reset=True)
                    continue

                # 3) Se asigna un proyecto nuevo
                project = self.env['project.project'].browse(proyecto_id_nuevo)
                #_logger.info(f"[Reserva] Order {order.name}: migrando etapas al proyecto {project.name} (#{project.id})")

                for line in order.material_reservation_ids:
                    old_stage = line.stage_id
                    if not old_stage:
                        _logger.debug(f"[Reserva] Linea {line.id}: sin etapa vieja, se omite")
                        continue

                    # Intentar encontrar etapa igual en el nuevo proyecto
                    etapa = Stage.search([
                        ('project_number', '=', project.obra_nr),
                        ('name',       '=', old_stage.name),
                    ], limit=1)

                    if etapa:
                        _logger.info(f"[Reserva] Reutilizo etapa “{etapa.name}” (#{etapa.id}) en proyecto {project.name}")
                    else:
                        etapa = Stage.create({
                            'name':       old_stage.name,
                            'project_number': project.obra_nr,
                            'deadline_date': old_stage.deadline_date or False,
                        })
                        #_logger.info(f"[Reserva] Creo etapa “{etapa.name}” (#{etapa.id}) en proyecto {project.name}")

                    line.stage_id = etapa.id
                    _logger.debug(f"[Reserva] Linea {line.id}: etapa reasignada a {etapa.name}")

                # 4) Actualizar campos de obra relacionada en la cabecera
                update_vals = {
                    'x_studio_nv_numero_de_obra_relacionada': project.obra_nr or False,
                    'x_studio_nv_numero_de_obra_padre': project.obra_padre_nr or False,
                }
                super(SaleOrder, order).write(update_vals)
                _logger.info(f"[Reserva] Order {order.name}: campos de obra relacionada actualizados {update_vals}")

                # 5) Actualizar distribución analítica
                order._update_analytic_distribution()
                _logger.debug(f"[Reserva] Order {order.name}: distribución analítica actualizada")

        return result
        
    
    # Actions
    
    def action_view_reservations(self):
        self.ensure_one()
        action = self.env.ref('stock.action_picking_tree_all').read()[0]
        pickings = self.sale_stock_link_id.picking_ids
        action['domain'] = [('id', 'in', pickings.ids)]
        return action

    
    def action_confirm(self):
        # Validar que todas las líneas de reserva de materiales tengan un stage_id
        missing_stage_lines = self.material_reservation_ids.filtered(lambda l: not l.stage_id)

        if missing_stage_lines:
            # Construir un mensaje con los productos o descripciones de las líneas sin etapa
            missing_info = "\n".join(
                [f"- Producto: {line.product_id.display_name}" for line in missing_stage_lines]
            )
            raise UserError(
                "No se puede confirmar la orden porque hay reservas de materiales sin una etapa asignada. "
                "Por favor, revisa las siguientes líneas:\n" + missing_info
            )



        # Pongo el almacen por defecto de odoo igual al almacen que cree yo
        self['warehouse_id'] = self.studio_almacen.id
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
        
        #self.delivery_count += 1  # Actualiza el contador de reserva
        
        self._compute_material_reservation_status()  # Recalcula el estado de la reserva


    def action_open_reservation_wizard(self):
        return {
            'name': 'Seleccionar Etapa para Reservas',
            'type': 'ir.actions.act_window',
            'res_model': 'reservation.report.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_project_number': self.x_studio_nv_numero_de_obra_relacionada
            }
        }

    

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
                
    
class MaterialReservationStage(models.Model):
    _name = 'material.reservation.stage'
    _description = 'Material Reservation Stage'

    material_line = fields.One2many(
        'sale.order.material.reservation.line','stage_id',
        string="Linea de Material",
        required=False,
        help="material reservation associated with the Stage.",
    )

    name = fields.Char(string="Stage Name", required=True)
    
    project_number = fields.Integer(
        string="Project Number", 
        help="Related project number.",
        compute="_compute_project_number",
        store=True  # Este campo ahora será almacenado
    )
    deadline_date = fields.Date(
        string="Delivery Deadline",
        help="Deadline for delivering all materials for this stage."
    )

    # En MaterialReservationStage (sale_order_material_reservation.py)
    @api.depends('material_line.order_id.x_studio_nv_numero_de_obra_relacionada')
    def _compute_project_number(self):
        for reservation in self:
            obras = reservation.material_line.mapped('order_id.x_studio_nv_numero_de_obra_relacionada')
            if obras:
                # Opción 1: Tomar el primer valor y mostrar advertencia
                reservation.project_number = obras[0]
                _logger.warning(f"Etapa {reservation.name} tiene múltiples obras: {obras}. Usando {obras[0]}")

                # Opción 2: Concatenar valores (ej: "123, 456")
                # reservation.project_number = ", ".join(map(str, set(obras)))
            else:
                reservation.project_number = False

    @api.model
    def create(self, vals):
        record = super().create(vals)
        #_logger.warning(f"Etapa: {record.name} con datos: {vals}")
        #_logger.warning(f"Numero de la obra papa: {record.material_line.order_id.x_studio_nv_numero_de_obra_relacionada}")

        record.project_number=record.material_line.order_id.x_studio_nv_numero_de_obra_relacionada
        
        return record

    
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
        string="Producto", 
        required=True
    )
    product_uom_qty = fields.Float(
        string="Cantidad", 
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
    stage_id = fields.Many2one(
        'material.reservation.stage',
        string="Etapa",
        required=True,
        help="Stage associated with the material reservation.",   
    )
    
    stage_deadline_date = fields.Date(
        string="Stage Deadline",
        related="stage_id.deadline_date",
        store=True,
        readonly=True,
        help="Deadline for the stage associated with this reservation line."
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
        _logger.warning(f"Entrando en el write de Linea de Reserva ")
        res = super().write(vals)
        updated_lines = []
        for line in self:
            if 'product_uom_qty' in vals:
                if vals['product_uom_qty'] < line.qty_done:
                    raise UserError(_("No puedes establecer una cantidad menor a la hecha."))
                line.qty_pending = max(0, vals['product_uom_qty'] - line.qty_done)
                #_logger.warning(f"cantidad pendiente {line.qty_pending} para la linea: {line.name}")
                updated_lines.append(line)

        
        if updated_lines:
            self._handle_material_reservation(updated_lines)
            _logger.warning(f"lineas_actualizadas {updated_lines}")
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
        _logger.warning(f"Entrando en _handle_material_reservation")
        """Handle creation or update of material reservations for multiple lines."""
        # Obtener las órdenes asociadas a las líneas.
        orders = {line.order_id for line in lines}
    
        for order in orders:
            # Filtrar pickings existentes que puedan ser reutilizados.
            pickings = order.sale_stock_link_id.picking_ids.filtered(
                lambda p: p.state not in ('done', 'cancel')
            )
            # Filtro por todos los pickings de tipo salida, excluyo los de tipo devolucion ( incoming )
            pickings = pickings.filtered( lambda p:p.picking_type_code in ('outgoing'))
    
            reusable_picking = pickings[:1]  # Tomar el primero válido si existe.
            lines_with_pending_qty = [line for line in lines if line.qty_pending >= 0]
    
            if reusable_picking:
                # Actualizar o agregar movimientos a un picking existente.
                for line in lines_with_pending_qty:
                    self._add_or_update_moves_in_picking(line, reusable_picking)
                    if reusable_picking.state == "draft":
                        reusable_picking.action_confirm()
                _logger.info(f"Movimientos actualizados o agregados al picking existente {reusable_picking.id}.")
            else:
                # Crear un nuevo picking y asignar movimientos.
                all_lines = self.env['sale.order'].browse(lines[0].order_id.id).material_reservation_ids
                _logger.warning(f"Todas las lineas {all_lines}")
                lines_with_pending_qty = [line for line in all_lines if line.qty_pending>=0]
                _logger.warning(f"lineas con cant pendientes {lines_with_pending_qty}")
                #raise UserError(f"Lineas papa")
                new_picking = self._create_new_picking_for_lines(order, lines_with_pending_qty)
                new_picking.action_confirm()
                _logger.info(f"Nuevo picking creado con ID {new_picking.id} para las líneas: {lines_with_pending_qty}.")


    def _add_or_update_moves_in_picking(self, line, picking):
        _logger.warning(f"Entrando en _add_or_update_moves_in_picking")
        """Add or update stock moves in an existing picking."""
        all_moves = picking.move_ids_without_package.filtered(lambda m: m.state not in ('done', 'cancel'))
        existing_moves = all_moves.filtered(
            lambda m: m.reservation_line_id == line
        )
        move_ids=[m.id for m in all_moves]
        #_logger.warning(f"movimientos existentes: {existing_moves}\n Todos los movimientos: {all_moves}")
        if existing_moves:
            for move in existing_moves:
                #_logger.warning(f"movimiente {move.name}")
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
                'date': fields.Datetime.now(),
                'state': 'assigned',  # Estado de movimiento asignado
                'reservation_line_id': line.id,
                'sale_stock_link_id':line.order_id.sale_stock_link_id.id,
                # Asegúrate de no establecer el sale_line_id
                'sale_line_id': False,
            })
            # Agrego la relacion de la linea de movimiento con la linea de la reserva
            line.move_ids = new_move
            # Añadir el ID del movimiento a la lista
            move_ids.append(new_move.id)

            #raise UserError(f"movimientos: {move_ids}  relacion de la linea {line.name} con el movimiento {line.move_ids}")
            # Asigna los IDs al campo 'move_id_without_package' usando Command.clear y Command.set
            picking['move_ids_without_package'] = [Command.clear(), Command.set(move_ids)]
            #_logger.warning(f"Nuevo movimiento creado en el picking {picking.id} para la línea {line.name}: {new_move}")

    

    def _create_new_picking_for_lines(self, order, lines):
        _logger.warning(f"****Entrando en _create_new_picking_for_lines")
        """Create a new picking for a set of lines with pending quantities."""
        new_picking = order._create_material_reservation_picking()
        move_ids=[]
        for line in lines:
            new_move = self.env['stock.move'].create({
                'name': line.product_id.name,
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty_pending,
                'product_uom': line.product_uom.id,
                'location_id': new_picking.picking_type_id.default_location_src_id.id,
                'location_dest_id': new_picking.location_dest_id.id,
                'picking_id': new_picking.id,
                'company_id': line.company_id.id,
                'date': fields.Datetime.now(),
                'state': 'assigned',  # Estado de movimiento asignado
                'reservation_line_id': line.id,
                'sale_stock_link_id':line.order_id.sale_stock_link_id.id,
                # Asegúrate de no establecer el sale_line_id
                'sale_line_id': False,
            })
            # Agrego la relacion de la linea de movimiento con la linea de la reserva
            line.move_ids = new_move
            # Añadir el ID del movimiento a la lista
            move_ids.append(new_move.id)
        
        new_picking['move_ids_without_package'] = [Command.clear(), Command.set(move_ids)]
        
        return new_picking

    # Constrains

    @api.constrains('product_id', 'stage_id')
    def _check_duplicate_product_stage(self):
        #_logger.warning(f"Entrando a _check_duplicate_product_stage")
        for line in self:
            lineas_without_me = self.search([
                ('id', '!=', line.id),
                ('order_id', '=', line.order_id.id)
            ])
            lineas_without_me = [(l.stage_id.name ,l.product_id.id) for l in lineas_without_me]
            #_logger.warning(f"lineas_without_me: {lineas_without_me}")
            duplicates=[]
            if (line.stage_id.name,line.product_id.id) in lineas_without_me:
                duplicates.append(line.id)
            else:
                _logger.warning(f"La linea {line.name} - etapa  {line.stage_id.name} no esta duplicada")
            
            if duplicates:
                raise ValidationError(_(f"No puedes agregar el mismo producto con la misma etapa."))



