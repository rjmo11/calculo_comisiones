from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class CalculoComision(models.Model):
    _name = 'calculo.comision'
    _description = 'Cálculo de Comisiones de Vendedores'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, default=lambda self: _('Nuevo'))
    vendedor_id = fields.Many2one(
        'hr.employee',
        string='Empleado Vendedor',
        required=True,
        tracking=True,
        domain=[('user_id', '!=', False)],
        help="Empleado del equipo de ventas. Debe tener un usuario de sistema vinculado."
    )
    # Usuario derivado del empleado: usado internamente para buscar facturas y equipos CRM
    user_id = fields.Many2one(
        'res.users',
        related='vendedor_id.user_id',
        string='Usuario del Vendedor',
        store=False,
        readonly=True,
    )
    fecha_inicio = fields.Date(string='Fecha Inicio', required=True, tracking=True)
    fecha_fin = fields.Date(string='Fecha Fin', required=True, tracking=True)
    meta_id = fields.Many2one('meta.vendedor', string='Meta Mensual', required=True, tracking=True)
    
    tipo_periodo = fields.Selection([
        ('mes', 'Mes Completo'),
        ('quincena1', '1ra Quincena (1-15)'),
        ('quincena2', '2da Quincena (Ajuste Mensual)'),
        ('personalizado', 'Personalizado')
    ], string='Tipo Técnico de Periodo', default='mes', required=True, tracking=True)

    modo_periodo = fields.Selection([
        ('mes', 'Mensual'),
        ('quincenal', 'Quincenal'),
        ('personalizado', 'Personalizado')
    ], string='Modo de Periodo', default='mes', required=True)
    
    quincena_elegida = fields.Selection([
        ('1', '1ra Quincena'),
        ('2', '2da Quincena')
    ], string='Quincena', default='1')
    
    importe_adelanto = fields.Monetary(string='Adelanto 1ra Quincena', currency_field='currency_id', readonly=True)
    
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('calculated', 'Calculado'),
        ('approved', 'Aprobado')
    ], string='Estado', default='draft', tracking=True)

    # Relación de Monedas y Metas (para mostrar comparaciones en la vista)
    currency_id = fields.Many2one('res.currency', related='meta_id.moneda_id', store=True, readonly=True)
    meta_venta = fields.Monetary(related='meta_id.meta_venta', string='Meta Venta Mensual')
    meta_cobranza = fields.Monetary(related='meta_id.meta_cobranza', string='Meta Cobranza Mensual')
    
    meta_venta_aplicada = fields.Monetary(string='Meta Venta Aplicada', currency_field='currency_id', readonly=True)
    meta_cobranza_aplicada = fields.Monetary(string='Meta Cobranza Aplicada', currency_field='currency_id', readonly=True)
    
    bono_base_venta = fields.Monetary(related='meta_id.bono_base_venta', string='Bono Base Venta Mensual')
    bono_base_cobranza = fields.Monetary(related='meta_id.bono_base_cobranza', string='Bono Base Cobranza Mensual')
    
    bono_base_venta_aplicado = fields.Monetary(string='Bono Base Venta Aplicado', currency_field='currency_id', readonly=True)
    bono_base_cobranza_aplicado = fields.Monetary(string='Bono Base Cobranza Aplicado', currency_field='currency_id', readonly=True)

    # Resultados Reales (Ventas y Cobranzas)
    venta_real_monto = fields.Monetary(string='Venta Real', currency_field='currency_id', readonly=True, tracking=True)
    cobranza_real_monto = fields.Monetary(string='Cobranza Real', currency_field='currency_id', readonly=True, tracking=True)
    
    # Cumplimiento
    porcentaje_cumplimiento_v = fields.Float(string='% Cumplimiento Venta', readonly=True)
    porcentaje_cumplimiento_c = fields.Float(string='% Cumplimiento Cobranza', readonly=True)
    
    # Pagos de Bono
    monto_bono_venta = fields.Monetary(string='Bono Venta Logrado', currency_field='currency_id', readonly=True)
    monto_bono_cobranza = fields.Monetary(string='Bono Cobranza Logrado', currency_field='currency_id', readonly=True)
    total_a_pagar = fields.Monetary(string='Total a Pagar', currency_field='currency_id', readonly=True, compute='_compute_total_a_pagar', store=True)

    # Relaciones One2Many (Dinámicas / Transientes para la vista)
    factura_ids = fields.Many2many('account.move', string='Facturas Recopiladas', readonly=True)
    pago_ids = fields.Many2many('account.payment', string='Pagos Recopilados', readonly=True)

    # Identificador de Rol (Útil para Reportes Estáticos)
    is_supervisor_role = fields.Boolean(
        string='Es Supervisor', 
        compute='_compute_is_supervisor_role'
    )

    @api.depends('vendedor_id')
    def _compute_is_supervisor_role(self):
        for record in self:
            uid = record.vendedor_id.user_id.id if record.vendedor_id.user_id else False
            record.is_supervisor_role = bool(
                uid and self.env['crm.team'].search_count([('user_id', '=', uid)])
            )

    @api.onchange('vendedor_id', 'fecha_inicio', 'modo_periodo', 'quincena_elegida')
    def _onchange_vendedor_periodo(self):
        """ Sincroniza la interactividad de la UI con la lógica técnica y fechas. 
            También limpia resultados anteriores para evitar errores de singleton en Odoo. 
        """
        import calendar
        from datetime import date
        today = fields.Date.today()
        base_date = self.fecha_inicio or today
        mes = base_date.month
        anio = base_date.year
        
        # Mapeo de Interactividad -> Lógica Técnica
        if self.modo_periodo == 'mes':
            self.tipo_periodo = 'mes'
            _wd, last_day = calendar.monthrange(anio, mes)
            self.fecha_inicio = date(anio, mes, 1)
            self.fecha_fin = date(anio, mes, last_day)
        elif self.modo_periodo == 'quincenal':
            if self.quincena_elegida == '1':
                self.tipo_periodo = 'quincena1'
                self.fecha_inicio = date(anio, mes, 1)
                self.fecha_fin = date(anio, mes, 15)
            else:
                self.tipo_periodo = 'quincena2'
                _wd, last_day = calendar.monthrange(anio, mes)
                self.fecha_inicio = date(anio, mes, 1) # Acumulado para ajuste
                self.fecha_fin = date(anio, mes, last_day)
        else:
            self.tipo_periodo = 'personalizado'
            
        # Búsqueda de Meta automática — usa user_id del empleado para domain en meta.vendedor
        if self.vendedor_id:
            meta = self.env['meta.vendedor'].search([
                ('vendedor_id', '=', self.vendedor_id.id),
                ('periodo_mes', '=', str(mes)),
                ('periodo_anio', '=', anio),
                ('state', '=', 'active')
            ], limit=1)
            if meta:
                self.meta_id = meta
        
        # LIMPIEZA DE SEGURIDAD: 
        # Si el usuario cambia el periodo, borramos los resultados anteriores para evitar 
        # inconsistencias visuales y errores técnicos de Odoo con múltiples registros.
        self.factura_ids = [(5, 0, 0)]
        self.pago_ids = [(5, 0, 0)]
        self.venta_real_monto = 0.0
        self.cobranza_real_monto = 0.0
        self.porcentaje_cumplimiento_v = 0.0
        self.porcentaje_cumplimiento_c = 0.0
        self.monto_bono_venta = 0.0
        self.monto_bono_cobranza = 0.0
        self.total_a_pagar = 0.0
        self.state = 'draft'

    @api.constrains('vendedor_id', 'fecha_inicio', 'fecha_fin', 'tipo_periodo')
    def _check_unique_periodo(self):
        for record in self:
            domain = [
                ('id', '!=', record.id),
                ('vendedor_id', '=', record.vendedor_id.id),
                ('tipo_periodo', '=', record.tipo_periodo),
                ('fecha_inicio', '=', record.fecha_inicio),
                ('fecha_fin', '=', record.fecha_fin),
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(_("Ya existe un cálculo de comisión de este tipo para este periodo."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('calculo.comision') or _('Nuevo')
        return super().create(vals_list)

    @api.depends('monto_bono_venta', 'monto_bono_cobranza', 'importe_adelanto')
    def _compute_total_a_pagar(self):
        for record in self:
            record.total_a_pagar = (record.monto_bono_venta + record.monto_bono_cobranza) - record.importe_adelanto

    def action_procesar_calculo(self):
        """ Motor de cálculo de comisiones por metas de ventas y cobranzas """
        for record in self:
            if not record.meta_id or not record.meta_id.esquema_id:
                raise UserError(_("El empleado no tiene una meta o un esquema de comisión asignado."))

            # ── Guardia de seguridad: el empleado debe tener usuario vinculado ──
            if not record.vendedor_id.user_id:
                raise UserError(
                    _("El empleado '%s' no tiene un usuario de sistema vinculado. "
                      "Ve a Empleados → edita el registro → campo 'Usuario Relacionado'."
                      ) % record.vendedor_id.name
                )

            meta = record.meta_id
            esquema = meta.esquema_id
            uid = record.vendedor_id.user_id.id  # ID del res.users para búsqueda de facturas

            # Buscamos si el empleado es líder de equipo CRM o tiene subordinados por RRHH (parent_id)
            equipos_liderados = self.env['crm.team'].search([('user_id', '=', uid)])
            vendedores_a_calcular = []
            
            if equipos_liderados:
                vendedores_a_calcular.extend(equipos_liderados.mapped('member_ids').ids)
                
            subordinados = self.env['hr.employee'].search([('parent_id', '=', record.vendedor_id.id)])
            if subordinados:
                vendedores_a_calcular.extend(subordinados.mapped('user_id').ids)
                
            vendedores_a_calcular = list(set([v for v in vendedores_a_calcular if v]))
            
            if not vendedores_a_calcular:
                vendedores_a_calcular = [uid]
            elif uid not in vendedores_a_calcular:
                vendedores_a_calcular.append(uid)

            # --- 1. CÁLCULO DE VENTAS ---
            # Buscar facturas (out_invoice), publicadas (posted), del equipo/vendedor en el rango de fechas
            facturas = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_user_id', 'in', vendedores_a_calcular),
                ('invoice_date', '>=', record.fecha_inicio),
                ('invoice_date', '<=', record.fecha_fin)
            ])
            # Sumar la base imponible (amount_untaxed)
            total_ventas = sum(facturas.mapped('amount_untaxed'))
            
            # --- 2. CÁLCULO DE COBRANZAS ---
            
            # Lógica de Cobranzas: Buscamos pagos en el rango
            pagos_periodo = self.env['account.payment'].search([
                ('date', '>=', record.fecha_inicio),
                ('date', '<=', record.fecha_fin),
                ('state', 'in', ('posted', 'paid')),
                ('payment_type', '=', 'inbound')
            ])
            
            pagos_vendedor = self.env['account.payment']
            for p in pagos_periodo:
                # Combinamos lógica: campo explícito OR creador OR facturas vinculadas
                if (p.vendedor_id.id in vendedores_a_calcular) or \
                   (p.create_uid.id in vendedores_a_calcular) or \
                   any(inv.invoice_user_id.id in vendedores_a_calcular for inv in p.reconciled_invoice_ids):
                    pagos_vendedor |= p
            
            total_cobranzas = sum(pagos_vendedor.mapped('amount'))

            # --- AJUSTE POR PERIODO (Prorrateo de Metas) ---
            factor_prorrateo = 1.0
            if record.tipo_periodo == 'quincena1':
                factor_prorrateo = 0.5  # 1ra quincena evalúa contra 50% de la meta
            
            meta_v_ajustada = meta.meta_venta * factor_prorrateo
            meta_c_ajustada = meta.meta_cobranza * factor_prorrateo

            # --- 3. EVALUACIÓN DE DESEMPEÑO ---
            # Ratio de cumplimiento contra meta ajustada
            ratio_v = (total_ventas / meta_v_ajustada) if meta_v_ajustada else 0.0
            ratio_c = (total_cobranzas / meta_c_ajustada) if meta_c_ajustada else 0.0

            def _get_factor(ratio):
                linea = self.env['esquema.comision.linea'].search([
                    ('esquema_id', '=', esquema.id),
                    ('cumplimiento_min', '<=', ratio),
                    ('cumplimiento_max', '>', ratio),
                ], limit=1)
                if linea:
                    return linea.factor_pago
                highest = self.env['esquema.comision.linea'].search([
                    ('esquema_id', '=', esquema.id)
                ], order='cumplimiento_max desc', limit=1)
                if highest and ratio >= highest.cumplimiento_max:
                    return highest.factor_pago
                return 0.0

            factor_v = _get_factor(ratio_v)
            factor_c = _get_factor(ratio_c)
            
            # El bono base NO se prorratea, se paga lo que dice la escala sobre el monto base
            # Pero si es Q1, pagamos solo el 50% del bono resultante de la escala? 
            # User dijo: "Opción 2: 1ra Q es un pago a cuenta, 2da Q es el ajuste".
            # Entonces en Q1, el bono base también debería verse afectado por el factor?
            # En realidad, si la meta se divide, el bono base tambien suele dividirse para Q1.
            monto_bono_v = (meta.bono_base_venta * factor_prorrateo) * factor_v
            monto_bono_c = (meta.bono_base_cobranza * factor_prorrateo) * factor_c
            
            # --- DETECCIÓN DE ADELANTO (Para Q2) ---
            adelanto = 0.0
            if record.tipo_periodo == 'quincena2':
                q1_calc = self.search([
                    ('vendedor_id', '=', record.vendedor_id.id),
                    ('meta_id', '=', record.meta_id.id),
                    ('tipo_periodo', '=', 'quincena1'),
                    ('state', '=', 'approved'),
                    ('id', '!=', record.id)
                ], limit=1)
                if q1_calc:
                    adelanto = q1_calc.total_a_pagar

            # Guardar Resultados Finales
            record.write({
                'venta_real_monto': total_ventas,
                'cobranza_real_monto': total_cobranzas,
                'meta_venta_aplicada': meta_v_ajustada,
                'meta_cobranza_aplicada': meta_c_ajustada,
                'bono_base_venta_aplicado': meta.bono_base_venta * factor_prorrateo,
                'bono_base_cobranza_aplicado': meta.bono_base_cobranza * factor_prorrateo,
                'porcentaje_cumplimiento_v': ratio_v,
                'porcentaje_cumplimiento_c': ratio_c,
                'monto_bono_venta': monto_bono_v,
                'monto_bono_cobranza': monto_bono_c,
                'importe_adelanto': adelanto,
                'factura_ids': [(6, 0, facturas.ids)],
                'pago_ids': [(6, 0, pagos_vendedor.ids)],
                'state': 'calculated'
            })
            
            # Dejar nota en el chatter
            #record.message_post(body=_("Cálculo procesado correctamente. Ventas: %s, Cobranzas: %s") % (total_ventas, total_cobranzas))

    def action_approve(self):
        for record in self:
            record.state = 'approved'
            
    def action_draft(self):
        for record in self:
            record.state = 'draft'

    def action_export_master_xlsx(self):
        """Redirige al controlador HTTP para generar el Excel de los registros activos."""
        if any(r.state not in ['calculated', 'approved'] for r in self):
            raise ValidationError(_("Solo se pueden exportar liquidaciones que estén en estado 'Calculado' o 'Aprobado' para evitar inconsistencias de recálculo."))
            
        ids_str = ','.join([str(record.id) for record in self])
        return {
            'type': 'ir.actions.act_url',
            'url': '/calculo_comisiones/export_xlsx?ids=%s' % ids_str,
            'target': 'self',
        }
