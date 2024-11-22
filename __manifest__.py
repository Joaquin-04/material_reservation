# __manifest__.py
{
    'name': 'Sale Material Reservation',
    'version': '1.0',
    'summary': 'Agregar una pestaña en la orden de venta para gestionar reservas de materiales.',
    'depends': ['sale_management','sale', 'stock'],
    'author': 'Tu Nombre',
    'category': 'Sales',
    'author': 'Your Name',
    'data': [
        'security/ir.model.access.csv',
        'views/sale_order_views.xml',
        'data/sale_stock_link_sequence.xml',  # Archivo de secuencia
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
