from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class CalculoComision(models.Model):
    _name = 'calculo.comision'
    _description = 'Cálculo de Comisiones de Vendedores'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Referencia', required=True, copy=False, readonly=True, default=lambda self: _('Nuevo'))
    vendedor_id = fields.Many2one('res.users', string='Vendedor', required=True, tracking=True)
    fecha_inicio = fields.Date(string='Fecha Inicio', required=True, tracking=True)
    fecha_fin = fields.Date(string='Fecha Fin', required=True, tracking=True)
    meta_id = fields.Many2one('meta.vendedor', string='Meta Mensual', required=True, tracking=True)
    
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('calculated', 'Calculado'),
        ('approved', 'Aprobado')
    ], string='Estado', default='draft', tracking=True)

    # Relación de Monedas y Metas (para mostrar comparaciones en la vista)
    currency_id = fields.Many2one('res.currency', related='meta_id.moneda_id')
    meta_venta = fields.Monetary(related='meta_id.meta_venta', string='Meta Venta')
    meta_cobranza = fields.Monetary(related='meta_id.meta_cobranza', string='Meta Cobranza')
    bono_base_venta = fields.Monetary(related='meta_id.bono_base_venta', string='Bono Base Venta')
    bono_base_cobranza = fields.Monetary(related='meta_id.bono_base_cobranza', string='Bono Base Cobranza')

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

    @api.constrains('vendedor_id', 'fecha_inicio', 'fecha_fin')
    def _check_unique_periodo(self):
        for record in self:
            domain = [
                ('id', '!=', record.id),
                ('vendedor_id', '=', record.vendedor_id.id),
                ('fecha_inicio', '<=', record.fecha_fin),
                ('fecha_fin', '>=', record.fecha_inicio),
            ]
            if self.search_count(domain) > 0:
                raise ValidationError(_("Ya existe un cálculo de comisión para este vendedor en el periodo seleccionado o uno que se solapa."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('calculo.comision') or _('Nuevo')
        return super().create(vals_list)

    @api.depends('monto_bono_venta', 'monto_bono_cobranza')
    def _compute_total_a_pagar(self):
        for record in self:
            record.total_a_pagar = record.monto_bono_venta + record.monto_bono_cobranza

    def action_procesar_calculo(self):
        """ Motor de cálculo de comisiones por metas de ventas y cobranzas """
        for record in self:
            if not record.meta_id or not record.meta_id.esquema_id:
                raise UserError(_("El vendedor no tiene una meta o un esquema de comisión asignado."))
                
            # --- 1. CÁLCULO DE VENTAS ---
            # Buscar facturas (out_invoice), publicadas (posted), del vendedor en el rango de fechas
            facturas = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted'),
                ('invoice_user_id', '=', record.vendedor_id.id),
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
                # Combinamos lógica: campo explícito OR creador OR facturas
                if (p.vendedor_id.id == record.vendedor_id.id) or \
                   (p.create_uid.id == record.vendedor_id.id) or \
                   any(inv.invoice_user_id.id == record.vendedor_id.id for inv in p.reconciled_invoice_ids):
                    pagos_vendedor |= p
            
            total_cobranzas = sum(pagos_vendedor.mapped('amount'))

            # --- 3. EVALUACIÓN DE DESEMPEÑO ---
            meta = record.meta_id
            esquema = meta.esquema_id
            
            # Ratio de cumplimiento (Para mostrar en widget -> 1.0 = 100%)
            ratio_v = (total_ventas / meta.meta_venta) if meta.meta_venta else 0.0
            ratio_c = (total_cobranzas / meta.meta_cobranza) if meta.meta_cobranza else 0.0

            # Buscar factores de pago (Buscamos la escala más alta alcanzada usando ratios decimales 0.0 - 1.0)
            escala = esquema.linea_escala_ids.sorted('cumplimiento_min')
            factor_v = 0.0
            factor_c = 0.0
            
            for linea in escala:
                if ratio_v >= linea.cumplimiento_min:
                    factor_v = linea.factor_pago
                if ratio_c >= linea.cumplimiento_min:
                    factor_c = linea.factor_pago
            
            # Guardar Resultados Finales
            record.write({
                'venta_real_monto': total_ventas,
                'cobranza_real_monto': total_cobranzas,
                'porcentaje_cumplimiento_v': ratio_v,
                'porcentaje_cumplimiento_c': ratio_c,
                'monto_bono_venta': meta.bono_base_venta * factor_v,
                'monto_bono_cobranza': meta.bono_base_cobranza * factor_c,
                'factura_ids': [(6, 0, facturas.ids)],
                'pago_ids': [(6, 0, pagos_vendedor.ids)],
                'state': 'calculated'
            })
            
            # Dejar nota en el chatter
            record.message_post(body=_("Cálculo procesado correctamente. Ventas: %s, Cobranzas: %s") % (total_ventas, total_cobranzas))

    def action_approve(self):
        for record in self:
            record.state = 'approved'
            
    def action_draft(self):
        for record in self:
            record.state = 'draft'
