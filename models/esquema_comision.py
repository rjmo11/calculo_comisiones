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

    @api.constrains('linea_escala_ids')
    def _check_continuidade_escalas(self):
        for record in self:
            if not record.linea_escala_ids:
                continue
            # Ordenar las líneas por cumplimiento mínimo
            lineas_ordenadas = record.linea_escala_ids.sorted('cumplimiento_min')
            
            # Verificar que no haya "huecos" entre escalas
            for i in range(len(lineas_ordenadas) - 1):
                actual = lineas_ordenadas[i]
                siguiente = lineas_ordenadas[i+1]
                
                # Usamos round para evitar errores minúsculos de precisión en floats
                if round(actual.cumplimiento_max, 4) != round(siguiente.cumplimiento_min, 4):
                    raise ValidationError(_(
                        "Las escalas deben ser continuas. La escala que termina en %s%% "
                        "debe coincidir con la siguiente que empieza en %s%%."
                    ) % (actual.cumplimiento_max, siguiente.cumplimiento_min))

class EsquemaComisionLinea(models.Model):
    _name = 'esquema.comision.linea'
    _description = 'Detalle de Escalas de Comisión'
    _order = 'cumplimiento_min'

    esquema_id = fields.Many2one('esquema.comision', string='Esquema', ondelete='cascade')
    cumplimiento_min = fields.Float(string='Cumplimiento Mínimo', required=True)
    cumplimiento_max = fields.Float(string='Cumplimiento Máximo', required=True)
    factor_pago = fields.Float(string='Factor de Pago (%)', required=True, help="Multiplicador del bono (ej. 0.8 para 80%)")

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
