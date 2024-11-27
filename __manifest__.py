# __manifest__.py
{
    'name': 'Sale Material Reservation',
    'version': '1.0',
    'summary': 'Agregar una pestaña en la orden de venta para gestionar reservas de materiales.',
    'depends': ['sale_management', 'stock'],
    'author': 'Tu Nombre',
    'category': 'Sale',
    'author': 'Your Name',
    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'data/sale_stock_link_sequence.xml',  # Archivo de secuencia
        'views/material_reservation_stage_views.xml',  # Nueva vista para etapas
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
