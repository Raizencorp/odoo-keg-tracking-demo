{
    'name': 'Returnable Keg Tracking - Inventory',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Delivery',
    'summary': 'Scan kegs on delivery orders: validating the delivery dispatches the kegs',
    'description': """
Bridge between Returnable Keg Tracking and Inventory, installed automatically when both are present.

* Kegs are scanned on the outgoing delivery order instead of the sales order.
* The delivery cannot be validated until the kegs loaded match the draught quantities shipped.
* Validating the delivery (including partial deliveries with backorders) dispatches the kegs,
  so delivered quantities, deposits and keg custody stay consistent.
    """,
    'author': 'Cyril Gainon',
    'license': 'LGPL-3',
    'depends': ['keg_tracking', 'sale_stock'],
    'data': [
        'security/keg_stock_security.xml',
        'views/stock_picking_views.xml',
        'views/keg_movement_views.xml',
    ],
    'auto_install': True,
    'installable': True,
}
