# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta

class MetaVendedor(models.Model):
    _name = 'meta.vendedor'
    _description = 'Metas Mensuales de Vendedor'
    _rec_name = 'vendedor_id'

    vendedor_id = fields.Many2one(
        'res.users', string='Vendedor', required=True,
        domain=[('share', '=', False), ('active', '=', True)],
        help="Usuario vendedor activo"
    )
    esquema_id = fields.Many2one(
        'esquema.comision', string='Esquema de Comisión', required=True
    )
    es_supervisor = fields.Boolean(string='¿Es Supervisor?', default=False)
    periodo_mes = fields.Selection([
        ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
        ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
        ('9', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre')
    ], string='Mes', required=True, default=lambda self: str(date.today().month))
    periodo_anio = fields.Integer(
        string='Año', required=True, default=lambda self: date.today().year
    )
    moneda_id = fields.Many2one(
        'res.currency', string='Moneda', required=True,
        default=lambda self: self.env.ref('base.VES').id or self.env.company.currency_id.id
    )
    state = fields.Selection([
        ('active', 'Activo'),
        ('inactive', 'Inactivo')
    ], string='Estado', default='active', required=True)
    
    meta_venta = fields.Monetary(string='Meta Venta', currency_field='moneda_id')
    meta_cobranza = fields.Monetary(string='Meta Cobranza', currency_field='moneda_id')
    bono_base_venta = fields.Monetary(string='Bono Base Venta', currency_field='moneda_id')
    bono_base_cobranza = fields.Monetary(string='Bono Base Cobranza', currency_field='moneda_id')

    _sql_constraints = [
        ('vendedor_periodo_unique', 'unique(vendedor_id, periodo_mes, periodo_anio)', 
         'El vendedor ya tiene una meta asignada para este periodo (mes/año).')
    ]

    def accion_duplicar_periodo(self):
        """ Copia las metas seleccionadas para el mes siguiente. """
        for record in self:
            current_date = date(int(record.periodo_anio), int(record.periodo_mes), 1)
            next_date = current_date + relativedelta(months=1)
            
            new_vals = {
                'vendedor_id': record.vendedor_id.id,
                'es_supervisor': record.es_supervisor,
                'periodo_mes': str(next_date.month),
                'periodo_anio': next_date.year,
                'moneda_id': record.moneda_id.id,
                'meta_venta': record.meta_venta,
                'meta_cobranza': record.meta_cobranza,
                'bono_base_venta': record.bono_base_venta,
                'bono_base_cobranza': record.bono_base_cobranza,
            }
            # Check if record already exists for avoid constraint error in batch
            exists = self.search([
                ('vendedor_id', '=', record.vendedor_id.id),
                ('periodo_mes', '=', str(next_date.month)),
                ('periodo_anio', '=', next_date.year)
            ])
            if not exists:
                self.create(new_vals)
        return True
