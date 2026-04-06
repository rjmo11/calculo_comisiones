# -*- coding: utf-8 -*-
{
    'name': "calculo_comisiones",

    'summary': "Módulo para la gestión y cálculo de comisiones por ventas y cobranzas",

    'description': """
    sistema de cálculo automático de remuneración variable para optimizar 
    la gestión de incentivos por ventas y cobranzas en una empresa
    distribuidora de consumo masivo.
    """,

    'author': "rjmo11",
    'website': "https://github.com/rjmo11",

    'category': 'Sales',
    'version': '1.0',

    'depends': ['base',
        'sale',
        'account',
        'mail',
        'crm'],

    'data': [
        'security/calculo_comisiones_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'report/reports.xml',
        'report/report_calculo_comision_templates.xml',
        'views/dashboard_comision_views.xml',
        'views/esquema_comision_views.xml',
        'views/meta_vendedor_views.xml',
        'views/calculo_comision_views.xml',
    ],

    'demo': [
        'demo/demo.xml',
    ],

    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3'
}

