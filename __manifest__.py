# __manifest__.py
{
    'name': 'Sale Material Reservation',
    'version': '1.1',
    'summary': 'Agregar una pestaña en la orden de venta para gestionar reservas de materiales.',
    'depends': ['sale_management', 'stock','Project_Custom'],
    'author': 'Tu Nombre',
    'category': 'Sale',
    'author': 'Your Name',
    'data': [
        'security/groups.xml',            # ✅ Grupo de usuarios
        'security/ir.model.access.csv',   # ✅ Reglas de acceso
        'views/sale_order_views.xml',
        'data/sale_stock_link_sequence.xml',  # Archivo de secuencia
        'views/material_reservation_stage_views.xml',  # Nueva vista para etapas
        'views/wizard_split_views.xml',
    ],
    'post_init_hook': 'migrate_old_material_reservation_stages',

    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
