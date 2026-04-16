# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import date
import calendar

class ComisionDashboardGeneral(models.TransientModel):
    _name = 'comision.dashboard.general'
    _description = 'Dashboard Gerencial (Singleton)'

    name = fields.Char(default='Vista Gerencial de Resultados')
    
    @api.model
    def _selection_equipos(self):
        """ Genera la lista de equipos dinámicamente desde el CRM """
        equipos = self.env['crm.team'].search([])
        return [('all', 'Toda la Empresa')] + [(str(e.id), e.name) for e in equipos]

    equipo_filter = fields.Selection(
        selection=_selection_equipos, 
        string='Filtrar por Equipo', 
        default='all', 
        required=True
    )
    
    # Global KPIs
    total_facturado = fields.Monetary(string='Total Facturado Mes', currency_field='currency_id')
    total_cobrado = fields.Monetary(string='Total Cobrado Mes', currency_field='currency_id')
    cumplimiento_general = fields.Float(string='% Cumplimiento Empresa')
    bono_total_estimado = fields.Monetary(string='Bonos a Liquidar', currency_field='currency_id')
    color_cumplimiento = fields.Char(string='Clase CSS de Color')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id.id)
    
    # Relación de Desglose para Eje X
    desglose_vendedores_ids = fields.One2many(
        'comision.dashboard.vendedor', 
        'dashboard_id', 
        string='Gráfico Horizontal de Vendedores'
    )

    def _prepare_dashboard_data(self, equipo_filter='all'):
        """ Lógica central de cálculo (Sin escrituras a DB) """
        today = date.today()
        user = self.env.user
        
        # --- SEGURIDAD ---
        vendedores_permitidos = []
        is_admin = user.has_group('calculo_comisiones.group_calculo_comisiones_admin')
        is_supervisor = user.has_group('calculo_comisiones.group_calculo_comisiones_supervisor')
        
        if is_admin:
            vendedores_permitidos = None
        elif is_supervisor:
            equipos = self.env['crm.team'].sudo().search([('user_id', '=', user.id)])
            # Obtenemos los IDs de empleados que tengan user_id en la lista de miembros
            member_user_ids = equipos.mapped('member_ids').ids
            if user.id not in member_user_ids:
                member_user_ids.append(user.id)
            # Buscar empleados por user_id
            empleados_permitidos = self.env['hr.employee'].sudo().search(
                [('user_id', 'in', member_user_ids)]
            )
            vendedores_permitidos = empleados_permitidos.ids
        else:
            # Vendedor individual: buscar su propio hr.employee
            mi_empleado = self.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
            vendedores_permitidos = [mi_empleado.id] if mi_empleado else []

        domain = [('periodo_anio', '=', today.year), ('periodo_mes', '=', str(today.month))]
        if vendedores_permitidos is not None:
            domain.append(('vendedor_id', 'in', vendedores_permitidos))
        if equipo_filter and equipo_filter != 'all' and equipo_filter.isdigit():
            equipo = self.env['crm.team'].sudo().browse(int(equipo_filter))
            # IDs de usuarios del equipo (miembros + líder)
            usuarios_equipo = equipo.member_ids.ids + ([equipo.user_id.id] if equipo.user_id else [])
            # Convertir a IDs de empleados
            empleados_equipo = self.env['hr.employee'].sudo().search(
                [('user_id', 'in', usuarios_equipo)]
            )
            domain.append(('vendedor_id', 'in', empleados_equipo.ids))

        metas_mes = self.env['meta.vendedor'].search(domain)
        
        t_facturado = t_cobrado = t_meta_v = t_bono = 0.0
        lineas = []

        for meta in metas_mes:
            # Solo sumamos al total general si NO es supervisor para evitar duplicidad
            if not meta.es_supervisor:
                t_facturado += meta.venta_real_actual
                t_cobrado += meta.cobranza_real_actual
                t_meta_v += meta.meta_venta_dinamica
            
            # El bono sí lo sumamos para todos (todos cobran)
            t_bono += meta.comision_proyectada
            
            lineas.append((0, 0, {
                'vendedor_id': meta.vendedor_id.id,
                'sin_usuario': not meta.vendedor_id.user_id,
                'es_supervisor': meta.es_supervisor,
                'rol_label': 'SUPERVISOR' if meta.es_supervisor else 'VENDEDOR',
                'meta_venta': meta.meta_venta_dinamica,
                'venta_lograda': meta.venta_real_actual,
                'progreso_porcentaje': meta.progreso_venta_pct,
                'meta_cobranza': meta.meta_cobranza_dinamica,
                'cobranza_lograda': meta.cobranza_real_actual,
                'progreso_cobranza_porcentaje': meta.progreso_cobranza_pct,
                'bono_estimado': meta.comision_proyectada,
                'currency_id': meta.moneda_id.id
            }))
            
        cumplimiento = (t_facturado / t_meta_v) if t_meta_v > 0 else 0.0
        color = 'border-success text-success'
        if cumplimiento < 0.7:
            color = 'border-danger text-danger'
        elif cumplimiento < 1.0:
            color = 'border-warning text-warning'

        return {
            'equipo_filter': equipo_filter,
            'total_facturado': t_facturado,
            'total_cobrado': t_cobrado,
            'bono_total_estimado': t_bono,
            'cumplimiento_general': cumplimiento,
            'color_cumplimiento': color,
            'desglose_vendedores_ids': lineas,
            'currency_id': self.env.company.currency_id.id
        }

    @api.model
    def action_get_dashboard(self):
        """ Invocación inicial desde el menú """
        vals = self._prepare_dashboard_data()
        return self.create(vals)

    @api.onchange('equipo_filter')
    def _onchange_equipo_filter(self):
        """ Recálculo dinámico sin crear registros basura en DB """
        vals = self._prepare_dashboard_data(equipo_filter=self.equipo_filter)
        
        self.total_facturado = vals['total_facturado']
        self.total_cobrado = vals['total_cobrado']
        self.bono_total_estimado = vals['bono_total_estimado']
        self.cumplimiento_general = vals['cumplimiento_general']
        self.color_cumplimiento = vals['color_cumplimiento']
        
        # Odoo onchange maneja el reemplazo de One2many automáticamente al asignar una lista de comandos
        self.desglose_vendedores_ids = [(5, 0, 0)] + vals['desglose_vendedores_ids']

class ComisionDashboardVendedor(models.TransientModel):
    _name = 'comision.dashboard.vendedor'
    _description = 'Detalle de Barras para Dashboard'

    dashboard_id = fields.Many2one('comision.dashboard.general', required=True, ondelete='cascade')
    vendedor_id = fields.Many2one('hr.employee', string='Empleado')
    sin_usuario = fields.Boolean(
        string='Sin Usuario Vinculado',
        default=False,
        help="True cuando el empleado no tiene un res.users asignado. Se usa para mostrar advertencia en la vista."
    )
    es_supervisor = fields.Boolean(string='Es Supervisor', store=False)
    rol_label = fields.Char(string='Rol')
    meta_venta = fields.Monetary(string='Meta Venta', currency_field='currency_id')
    venta_lograda = fields.Monetary(string='Logro Venta', currency_field='currency_id')
    progreso_porcentaje = fields.Float(string='Termómetro de Ventas')
    meta_cobranza = fields.Monetary(string='Meta Cobranza', currency_field='currency_id')
    cobranza_lograda = fields.Monetary(string='Logro Cobranza', currency_field='currency_id')
    progreso_cobranza_porcentaje = fields.Float(string='Termómetro de Cobranza')
    bono_estimado = fields.Monetary(string='Bono Estimado', currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', string="Moneda")
