# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar

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

    # --- CAMPOS COMPUTADOS PARA DASHBOARD (EN VIVO) ---
    is_current_month = fields.Boolean(string='Es Mes Actual', compute='_compute_is_current_month', search='_search_is_current_month')
    venta_real_actual = fields.Monetary(string='Venta Real Actual', currency_field='moneda_id', compute='_compute_dashboard_metrics')
    cobranza_real_actual = fields.Monetary(string='Cobranza Real Actual', currency_field='moneda_id', compute='_compute_dashboard_metrics')
    progreso_venta_pct = fields.Float(string='% Cumplimiento Venta', compute='_compute_dashboard_metrics')
    progreso_cobranza_pct = fields.Float(string='% Cumplimiento Cobranza', compute='_compute_dashboard_metrics')
    comision_proyectada = fields.Monetary(string='Comisión Proyectada', currency_field='moneda_id', compute='_compute_dashboard_metrics')

    def _compute_is_current_month(self):
        today = fields.Date.context_today(self)
        for record in self:
            record.is_current_month = (str(record.periodo_anio) == str(today.year) and str(record.periodo_mes) == str(today.month))

    def _search_is_current_month(self, operator, value):
        if operator != '=' or not value:
            return []
        today = fields.Date.context_today(self)
        return [('periodo_anio', '=', today.year), ('periodo_mes', '=', str(today.month))]

    def _compute_dashboard_metrics(self):
        """Calcula el progreso de ventas y cobranzas para el mes vigente."""
        for record in self:
            # Init base values
            record.venta_real_actual = 0.0
            record.cobranza_real_actual = 0.0
            record.progreso_venta_pct = 0.0
            record.progreso_cobranza_pct = 0.0
            record.comision_proyectada = 0.0

            if not record.periodo_anio or not record.periodo_mes:
                continue

            try:
                mes = int(record.periodo_mes)
                anio = int(record.periodo_anio)
                _, ultimo_dia = calendar.monthrange(anio, mes)
                fecha_inicio = date(anio, mes, 1)
                fecha_fin = date(anio, mes, ultimo_dia)
            except ValueError:
                continue

            # Reutiliza la lógica de rol (vendedor/equipo) del calculo de comisión
            equipos_liderados = self.env['crm.team'].search([('user_id', '=', record.vendedor_id.id)])
            if equipos_liderados:
                vendedores_a_calcular = equipos_liderados.mapped('member_ids').ids
                if record.vendedor_id.id not in vendedores_a_calcular:
                    vendedores_a_calcular.append(record.vendedor_id.id)
            else:
                vendedores_a_calcular = [record.vendedor_id.id]

            # 1. Ventas
            facturas = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_user_id', 'in', vendedores_a_calcular),
                ('invoice_date', '>=', fecha_inicio),
                ('invoice_date', '<=', fecha_fin)
            ])
            total_ventas = sum(facturas.mapped('amount_untaxed'))
            record.venta_real_actual = total_ventas

            # 2. Cobranzas
            pagos_periodo = self.env['account.payment'].search([
                ('date', '>=', fecha_inicio),
                ('date', '<=', fecha_fin),
                ('state', 'in', ('posted', 'paid')),
                ('payment_type', '=', 'inbound')
            ])
            
            # TODO: Ideal usar dependencias si pago no tiene `vendedor_id`. Asumimos la estructura custom está.
            total_cobranzas = 0.0
            for p in pagos_periodo:
                v_id_has_payment = False
                if hasattr(p, 'vendedor_id') and p.vendedor_id.id in vendedores_a_calcular:
                    v_id_has_payment = True
                
                if v_id_has_payment or \
                   (p.create_uid.id in vendedores_a_calcular) or \
                   any(inv.invoice_user_id.id in vendedores_a_calcular for inv in p.reconciled_invoice_ids):
                    total_cobranzas += p.amount
            record.cobranza_real_actual = total_cobranzas

            # 3. Cumplimiento
            ratio_v = (total_ventas / record.meta_venta) if record.meta_venta else 0.0
            ratio_c = (total_cobranzas / record.meta_cobranza) if record.meta_cobranza else 0.0
            
            # Limitar visualmente pero mantener la lógica base
            record.progreso_venta_pct = min(ratio_v * 100.0, 100.0)
            record.progreso_cobranza_pct = min(ratio_c * 100.0, 100.0)

            # 4. Proyección Odoo ORM (usando intervalo [a, b))
            esquema = record.esquema_id
            if esquema:
                def _get_factor(ratio):
                    linea = self.env['esquema.comision.linea'].search([
                        ('esquema_id', '=', esquema.id),
                        ('cumplimiento_min', '<=', ratio),
                        ('cumplimiento_max', '>', ratio),
                    ], limit=1)
                    return linea.factor_pago if linea else 0.0

                factor_v = _get_factor(ratio_v)
                factor_c = _get_factor(ratio_c)
                record.comision_proyectada = (record.bono_base_venta * factor_v) + (record.bono_base_cobranza * factor_c)

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
