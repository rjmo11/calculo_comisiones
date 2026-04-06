# -*- coding: utf-8 -*-
from odoo import models, fields, api

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    # Campo sombra para guardar la preferencia manual
    vendedor_manual_id = fields.Many2one('res.users', string='Vendedor Oculto')

    vendedor_id = fields.Many2one(
        'res.users', 
        string='Vendedor (Cobranza)', 
        compute='_compute_vendedor_id', 
        inverse='_inverse_vendedor_id',
        store=False, # Computado al vuelo para garantizar lectura de conciliaciones tardías 
        help="Vendedor responsable de esta cobranza. "
             "Extraído de la factura conciliada o del cliente. Modificable manualmente."
    )

    @api.depends('reconciled_invoice_ids', 'vendedor_manual_id', 'partner_id')
    def _compute_vendedor_id(self):
        for payment in self:
            if payment.vendedor_manual_id:
                payment.vendedor_id = payment.vendedor_manual_id
            elif payment.reconciled_invoice_ids:
                invoices = payment.reconciled_invoice_ids.filtered(lambda inv: inv.move_type == 'out_invoice')
                if invoices and invoices[0].invoice_user_id:
                    payment.vendedor_id = invoices[0].invoice_user_id.id
                else:
                    payment.vendedor_id = payment.partner_id.user_id.id or False
            else:
                # Fallback al comercial del cliente si no hay facturas
                payment.vendedor_id = payment.partner_id.user_id.id or False

    def _inverse_vendedor_id(self):
        for payment in self:
            payment.vendedor_manual_id = payment.vendedor_id
