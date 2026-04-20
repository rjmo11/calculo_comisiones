# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import date
import calendar

class ComisionDashboardGeneral(models.TransientModel):
    _name = 'comision.dashboard.general'
    _description = 'Dashboard Gerencial (Singleton)'

    name = fields.Char(default='Vista Gerencial de Resultados')
    
    @api.model
    def _selection_departamentos(self):
        """ Genera la lista dinámicamente desde Departamentos de RRHH """
        departamentos = self.env['hr.department'].search([])
        return [('all', 'Toda la Empresa')] + [(str(d.id), d.name) for d in departamentos]

    departamento_filter = fields.Selection(
        selection=_selection_departamentos, 
        string='Filtrar por Departamento', 
        default='all', 
        required=True
    )
    
    filtro_anio = fields.Selection([(str(y), str(y)) for y in range(2020, 2035)], string='Año', default=lambda self: str(date.today().year), required=True)
    filtro_mes = fields.Selection([
        ('1', 'Enero'), ('2', 'Febrero'), ('3', 'Marzo'), ('4', 'Abril'),
        ('5', 'Mayo'), ('6', 'Junio'), ('7', 'Julio'), ('8', 'Agosto'),
        ('9', 'Septiembre'), ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre')
    ], string='Mes', default=lambda self: str(date.today().month), required=True)
    
    filtro_vendedor_id = fields.Many2one('hr.employee', string='Filtro Vendedor')
    
    filtro_corte = fields.Selection([
        ('todo', 'Mes Completo'),
        ('q1', '1ra Quincena'),
        ('q2', '2da Quincena'),
        ('s1', 'Semana 1'),
        ('s2', 'Semana 2'),
        ('s3', 'Semana 3'),
        ('s4', 'Semana 4')
    ], string='Corte Temporal', default='todo', required=True)
    
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

    def _prepare_dashboard_data(self, departamento_filter='all', mes=None, anio=None, vendedor_id=False, corte='todo'):
        """ Lógica central de cálculo (Sin escrituras a DB) """
        today = date.today()
        mes = mes or str(today.month)
        anio = anio or str(today.year)
        user = self.env.user
        
        # --- SEGURIDAD ---
        vendedores_permitidos = []
        is_admin = user.has_group('calculo_comisiones.group_calculo_comisiones_admin')
        is_supervisor = user.has_group('calculo_comisiones.group_calculo_comisiones_supervisor')
        
        if is_admin:
            vendedores_permitidos = None
        elif is_supervisor:
            equipos = self.env['crm.team'].sudo().search([('user_id', '=', user.id)])
            member_user_ids = equipos.mapped('member_ids').ids
            
            # Buscar empleados: Los del equipo CRM, los subordinados por jerarquía RRHH, y el propio supervisor
            empleados_permitidos = self.env['hr.employee'].sudo().search([
                '|', '|',
                ('user_id', 'in', member_user_ids),
                ('parent_id.user_id', '=', user.id),
                ('user_id', '=', user.id)
            ])
            vendedores_permitidos = empleados_permitidos.ids
        else:
            # Vendedor individual: buscar su propio hr.employee
            mi_empleado = self.env['hr.employee'].sudo().search(
                [('user_id', '=', user.id)], limit=1
            )
            vendedores_permitidos = [mi_empleado.id] if mi_empleado else []

        domain = [('periodo_anio', '=', int(anio)), ('periodo_mes', '=', mes)]
        
        if vendedor_id:
            # Si se busca un vendedor especifico, comprobar si está permitido
            if vendedores_permitidos is not None and vendedor_id not in vendedores_permitidos:
                domain.append(('vendedor_id', '=', -1)) # Bloquear acceso
            else:
                domain.append(('vendedor_id', '=', vendedor_id))
        else:
            if vendedores_permitidos is not None:
                domain.append(('vendedor_id', 'in', vendedores_permitidos))
            if departamento_filter and departamento_filter != 'all' and departamento_filter.isdigit():
                # Buscar empleados que formen parte del departamento elegido o de sus sub-departamentos (child_of)
                empleados_dept = self.env['hr.employee'].sudo().search(
                    [('department_id', 'child_of', int(departamento_filter))]
                )
                domain.append(('vendedor_id', 'in', empleados_dept.ids))
                
        # Pasar variable de corte en el contexto
        metas_mes = self.env['meta.vendedor'].with_context(dashboard_corte=corte).search(domain)
        
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
            'departamento_filter': departamento_filter,
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

    @api.onchange('departamento_filter', 'filtro_mes', 'filtro_anio', 'filtro_vendedor_id', 'filtro_corte')
    def _onchange_filtros(self):
        """ Recálculo dinámico """
        vals = self._prepare_dashboard_data(
            departamento_filter=self.departamento_filter,
            mes=self.filtro_mes,
            anio=self.filtro_anio,
            vendedor_id=self.filtro_vendedor_id.id if self.filtro_vendedor_id else False,
            corte=self.filtro_corte
        )
        
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
