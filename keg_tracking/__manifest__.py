{
    'name': 'Returnable Keg Tracking',
    'version': '18.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Track every keg by serial number: custody, deposits, returns, overdue and lost kegs',
    'description': """
Returnable Keg Tracking for breweries and beverage distributors
===============================================================
* One record per physical keg (serial number) with a full custody history
* Fill, dispatch on sales orders, return and clean kegs with scanner-friendly wizards
* Deposits added automatically to sales orders and refunded exactly on return
* Daily reminders for kegs held beyond their rotation target
* Lost kegs invoiced at replacement value minus the deposit retained
    """,
    'author': 'Cyril Gainon',
    'license': 'LGPL-3',
    'depends': ['sale_management'],
    'data': [
        'security/keg_security.xml',
        'security/ir.model.access.csv',
        'data/mail_activity_type_data.xml',
        'data/ir_cron_data.xml',
        'views/keg_type_views.xml',
        'views/keg_movement_views.xml',
        'views/keg_views.xml',
        'wizard/keg_fill_wizard_views.xml',
        'wizard/keg_dispatch_wizard_views.xml',
        'wizard/keg_return_wizard_views.xml',
        'wizard/keg_lost_wizard_views.xml',
        'views/product_template_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/keg_menus.xml',
    ],
    'demo': [
        'demo/keg_demo.xml',
    ],
    'application': True,
    'installable': True,
}
