# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import date
from dateutil.relativedelta import relativedelta
import calendar

class MetaVendedor(models.Model):
    _name = 'meta.vendedor'
    _description = 'Metas Mensuales de Vendedor'

    vendedor_id = fields.Many2one(
        'hr.employee', string='Vendedor', required=True,
        domain=[('user_id', '!=', False)],
        help="Empleado vendedor vinculado a un usuario de sistema"
    )
    # Campo relacionado para mantener retrocompatibilidad con la lógica de facturas
    user_id = fields.Many2one(
        'res.users',
        related='vendedor_id.user_id',
        string='Usuario del Vendedor',
        store=False,
        readonly=True,
    )
    # Rastro del departamento eliminado para favorecer flexibilidad dinámica por equipos estándar.
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
        string='Año', required=True, default=lambda self: date.today().year,
        group_operator=False
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
         'El empleado ya tiene una meta asignada para este periodo (mes/año).')
    ]

    @api.depends('vendedor_id', 'periodo_mes', 'periodo_anio')
    def _compute_display_name(self):
        for record in self:
            mes_label = dict(self._fields['periodo_mes'].selection).get(record.periodo_mes, '')
            record.display_name = f"{record.vendedor_id.name} ({mes_label} {record.periodo_anio})"

    def action_open_calculo_comision(self):
        """Abre o crea automáticamente el cálculo de comisión para el periodo de la meta actual."""
        self.ensure_one()
        
        CalculoObj = self.env['calculo.comision']
        calculo = CalculoObj.search([('meta_id', '=', self.id)], order='id desc', limit=1)
        
        if not calculo:
            # Guardia: el empleado debe tener usuario vinculado
            if not self.vendedor_id.user_id:
                from odoo.exceptions import UserError
                raise UserError(
                    f"El empleado '{self.vendedor_id.name}' no tiene un usuario de sistema vinculado. "
                    "Ve a Empleados y asigna el campo 'Usuario Relacionado' antes de continuar."
                )
            try:
                mes = int(self.periodo_mes)
                anio = int(self.periodo_anio)
                _weekday, ultimo_dia = calendar.monthrange(anio, mes)
                fecha_inicio = date(anio, mes, 1)
                fecha_fin = date(anio, mes, ultimo_dia)
            except ValueError:
                fecha_inicio = fields.Date.today()
                fecha_fin = fields.Date.today()
                
            calculo = CalculoObj.create({
                'vendedor_id': self.vendedor_id.id,
                'fecha_inicio': fecha_inicio,
                'fecha_fin': fecha_fin,
                'meta_id': self.id,
                'state': 'draft'
            })
            
            # Procedemos a autocalcular la liquidación a la fecha para evitar doble-clic manual
            try:
                calculo.action_procesar_calculo()
            except Exception:
                pass

        return {
            'type': 'ir.actions.act_window',
            'name': _('Liquidación Oficial'),
            'res_model': 'calculo.comision',
            'res_id': calculo.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # --- CAMPOS COMPUTADOS PARA DASHBOARD (EN VIVO) ---
    is_current_month = fields.Boolean(string='Es Mes Actual', compute='_compute_is_current_month', search='_search_is_current_month')
    meta_venta_dinamica = fields.Monetary(string='Meta Venta Dinámica', currency_field='moneda_id', compute='_compute_dashboard_metrics')
    meta_cobranza_dinamica = fields.Monetary(string='Meta Cobranza Dinámica', currency_field='moneda_id', compute='_compute_dashboard_metrics')
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
            record.meta_venta_dinamica = record.meta_venta
            record.meta_cobranza_dinamica = record.meta_cobranza

            if not record.periodo_anio or not record.periodo_mes:
                continue

            try:
                mes = int(record.periodo_mes)
                anio = int(record.periodo_anio)
                _weekday, ultimo_dia = calendar.monthrange(anio, mes)
                
                fecha_inicio = date(anio, mes, 1)
                fecha_fin = date(anio, mes, ultimo_dia)
                
                corte = self.env.context.get('dashboard_corte', 'todo')
                if corte == 'q1':
                    fecha_fin = date(anio, mes, 15)
                elif corte == 'q2':
                    fecha_inicio = date(anio, mes, 16)
                elif corte == 's1':
                    fecha_fin = date(anio, mes, min(7, ultimo_dia))
                elif corte == 's2':
                    fecha_inicio = date(anio, mes, 8)
                    fecha_fin = date(anio, mes, min(14, ultimo_dia))
                elif corte == 's3':
                    fecha_inicio = date(anio, mes, 15)
                    fecha_fin = date(anio, mes, min(21, ultimo_dia))
                elif corte == 's4':
                    fecha_inicio = date(anio, mes, 22)
            except ValueError:
                continue

            # Reutiliza la lógica de rol (vendedor/equipo) del calculo de comisión
            # Ahora obtenemos el user_id desde el empleado para buscar facturas
            uid = record.vendedor_id.user_id.id if record.vendedor_id.user_id else False
            if not uid:
                # Sin usuario vinculado: mostrar ceros, no crashear
                continue

            equipos_liderados = self.env['crm.team'].search([('user_id', '=', uid)])
            vendedores_a_calcular = []
            
            if equipos_liderados:
                vendedores_a_calcular.extend(equipos_liderados.mapped('member_ids').ids)
                
            # Agregar soporte por si el supervisor usa la jerarquía nativa de Empleados (parent_id)
            subordinados = self.env['hr.employee'].search([('parent_id', '=', record.vendedor_id.id)])
            if subordinados:
                vendedores_a_calcular.extend(subordinados.mapped('user_id').ids)
                
            vendedores_a_calcular = list(set([v for v in vendedores_a_calcular if v]))
            
            if not vendedores_a_calcular:
                vendedores_a_calcular = [uid]
            elif uid not in vendedores_a_calcular:
                vendedores_a_calcular.append(uid)

            # --- DYNAMIC METAS FOR SUPERVISORS ---
            meta_v_efectiva = record.meta_venta
            meta_c_efectiva = record.meta_cobranza

            if record.es_supervisor:
                member_user_ids = [m_id for m_id in vendedores_a_calcular if m_id != uid]
                if member_user_ids:
                    emp_miembros = self.env['hr.employee'].search([('user_id', 'in', member_user_ids)])
                    if emp_miembros:
                        metas_equipo = self.env['meta.vendedor'].search([
                            ('vendedor_id', 'in', emp_miembros.ids),
                            ('periodo_anio', '=', record.periodo_anio),
                            ('periodo_mes', '=', record.periodo_mes)
                        ])
                        meta_v_efectiva += sum(metas_equipo.mapped('meta_venta'))
                        meta_c_efectiva += sum(metas_equipo.mapped('meta_cobranza'))

            record.meta_venta_dinamica = meta_v_efectiva
            record.meta_cobranza_dinamica = meta_c_efectiva

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
            ratio_v = (total_ventas / meta_v_efectiva) if meta_v_efectiva else 0.0
            ratio_c = (total_cobranzas / meta_c_efectiva) if meta_c_efectiva else 0.0
            
            # Limitar visualmente pero mantener la lógica base
            record.progreso_venta_pct = ratio_v * 100.0
            record.progreso_cobranza_pct = ratio_c * 100.0

            # 4. Proyección Odoo ORM (usando intervalo [a, b))
            esquema = record.esquema_id
            if esquema:
                def _get_factor(ratio):
                    linea = self.env['esquema.comision.linea'].search([
                        ('esquema_id', '=', esquema.id),
                        ('cumplimiento_min', '<=', ratio),
                        ('cumplimiento_max', '>', ratio),
                    ], limit=1)
                    if linea:
                        return linea.factor_pago
                    
                    # Si el ratio supera la última escala definida, aplicar la máxima
                    highest = self.env['esquema.comision.linea'].search([
                        ('esquema_id', '=', esquema.id)
                    ], order='cumplimiento_max desc', limit=1)
                    
                    if highest and ratio >= highest.cumplimiento_max:
                        return highest.factor_pago
                        
                    return 0.0

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
