from odoo import models, fields

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    vendedor_id = fields.Many2one(
        'res.users', 
        string="Vendedor (Comisiones)", 
        help="Vendedor asignado explícitamente para el cálculo de comisiones. Si está vacío, se usará el creador o las facturas conciliadas."
    )
