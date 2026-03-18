# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError

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

    # Resultados Reales (Ventas y Cobranzas)
    venta_real_monto = fields.Float(string='Venta Real', readonly=True, tracking=True)
    cobranza_real_monto = fields.Float(string='Cobranza Real', readonly=True, tracking=True)
    
    # Cumplimiento
    porcentaje_cumplimiento_v = fields.Float(string='% Cumplimiento Venta', readonly=True)
    porcentaje_cumplimiento_c = fields.Float(string='% Cumplimiento Cobranza', readonly=True)
    
    # Pagos de Bono
    monto_bono_venta = fields.Float(string='Bono Venta', readonly=True)
    monto_bono_cobranza = fields.Float(string='Bono Cobranza', readonly=True)
    total_a_pagar = fields.Float(string='Total a Pagar', readonly=True, compute='_compute_total_a_pagar', store=True)

    # Relaciones One2Many (Dinámicas / Transientes para la vista)
    factura_ids = fields.Many2many('account.move', string='Facturas Recopiladas', readonly=True)
    pago_ids = fields.Many2many('account.payment', string='Pagos Recopilados', readonly=True)

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
            # Buscar pagos asociados al vendedor. En Odoo los pagos suelen atarse al partner, 
            # pero podemos buscar pagos donde el partner tenga a este vendedor asignado (user_id).
            pagos = self.env['account.payment'].search([
                ('state', '=', 'posted'),
                ('payment_type', '=', 'inbound'),
                ('partner_id.user_id', '=', record.vendedor_id.id),
                ('date', '>=', record.fecha_inicio),
                ('date', '<=', record.fecha_fin)
            ])
            total_cobranzas = sum(pagos.mapped('amount'))

            # --- 3. EVALUACIÓN DE DESEMPEÑO ---
            meta = record.meta_id
            esquema = meta.esquema_id
            
            # Evitar división por cero
            cumpl_venta = (total_ventas / meta.meta_venta * 100) if meta.meta_venta else 0.0
            cumpl_cobranza = (total_cobranzas / meta.meta_cobranza * 100) if meta.meta_cobranza else 0.0

            # Buscar factor de pago en la escala
            factor_venta = 0.0
            factor_cobranza = 0.0

            for linea in esquema.linea_escala_ids:
                if linea.cumplimiento_min <= cumpl_venta < linea.cumplimiento_max:
                    factor_venta = linea.factor_pago
                if linea.cumplimiento_min <= cumpl_cobranza < linea.cumplimiento_max:
                    factor_cobranza = linea.factor_pago

            # Guardar Resultados
            record.write({
                'venta_real_monto': total_ventas,
                'cobranza_real_monto': total_cobranzas,
                'porcentaje_cumplimiento_v': cumpl_venta,
                'porcentaje_cumplimiento_c': cumpl_cobranza,
                'monto_bono_venta': meta.bono_base_venta * (factor_venta / 100.0),
                'monto_bono_cobranza': meta.bono_base_cobranza * (factor_cobranza / 100.0),
                'factura_ids': [(6, 0, facturas.ids)],
                'pago_ids': [(6, 0, pagos.ids)],
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
