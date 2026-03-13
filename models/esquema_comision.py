# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class EsquemaComision(models.Model):
    _name = 'esquema.comision'
    _description = 'Esquema de Comisión'
    _rec_name = 'nombre'

    nombre = fields.Char(string='Nombre del Esquema', required=True)
    linea_escala_ids = fields.One2many(
        'esquema.comision.linea', 'esquema_id', string='Líneas de Escala'
    )

class EsquemaComisionLinea(models.Model):
    _name = 'esquema.comision.linea'
    _description = 'Detalle de Escalas de Comisión'
    _order = 'cumplimiento_min'

    esquema_id = fields.Many2one('esquema.comision', string='Esquema', ondelete='cascade')
    cumplimiento_min = fields.Float(string='% Cumplimiento Mínimo', required=True)
    cumplimiento_max = fields.Float(string='% Cumplimiento Máximo', required=True)
    factor_pago = fields.Float(string='Factor de Pago', required=True, help="Multiplicador del bono (ej. 0.8 para 80%)")

    @api.constrains('cumplimiento_min', 'cumplimiento_max')
    def _check_rangos(self):
        for record in self:
            if record.cumplimiento_min >= record.cumplimiento_max:
                raise ValidationError(_("El cumplimiento mínimo debe ser menor al máximo."))
            
            # Verificar solapamiento con otras líneas del mismo esquema
            overlapping = self.search([
                ('esquema_id', '=', record.esquema_id.id),
                ('id', '!=', record.id),
                '|', '|',
                '&', ('cumplimiento_min', '<=', record.cumplimiento_min), ('cumplimiento_max', '>', record.cumplimiento_min),
                '&', ('cumplimiento_min', '<', record.cumplimiento_max), ('cumplimiento_max', '>=', record.cumplimiento_max),
                '&', ('cumplimiento_min', '>=', record.cumplimiento_min), ('cumplimiento_max', '<=', record.cumplimiento_max)
            ])
            if overlapping:
                raise ValidationError(_("Los rangos de cumplimiento no pueden solaparse."))
