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

    # --- Campos de solo-lectura para mostrar los símbolos del intervalo semiabierto [min, max) ---
    limite_inferior_display = fields.Char(
        string='Límite Inferior (≥)',
        compute='_compute_display_fields',
        store=False,
        help="Muestra '≥ X%' indicando que el intervalo es cerrado por la izquierda"
    )
    limite_superior_display = fields.Char(
        string='Límite Superior (<)',
        compute='_compute_display_fields',
        store=False,
        help="Muestra '< X%' indicando que el intervalo es abierto por la derecha"
    )
    rango_display = fields.Char(
        string='Rango Completo',
        compute='_compute_display_fields',
        store=False,
        help="Descripción legible del intervalo semiabierto [min, max)"
    )

    @api.depends('cumplimiento_min', 'cumplimiento_max')
    def _compute_display_fields(self):
        """Genera los campos de visualización con la notación de intervalo semiabierto [min, max).
        
        Nota: los valores se almacenan como ratios decimales (ej. 0.79 = 79%).
        Si tus campos guardan porcentajes directos (ej. 79), elimina el * 100.
        """
        for record in self:
            def fmt(v):
                # Multiplica por 100 si los campos son ratios (0.0-1.0)
                # Cambia a solo '{:g}'.format(round(v, 6)) si ya son porcentajes directos
                pct = round(v * 100, 6)
                return '{:g}'.format(pct)

            min_str = fmt(record.cumplimiento_min)
            max_str = fmt(record.cumplimiento_max)
            record.limite_inferior_display = '\u2265 %s%%' % min_str   # ≥ símbolo
            record.limite_superior_display = '< %s%%' % max_str
            record.rango_display = _('Desde %s%% hasta menos de %s%%') % (min_str, max_str)

    @api.constrains('cumplimiento_min', 'cumplimiento_max')
    def _check_rangos(self):
        for record in self:
            if record.cumplimiento_min >= record.cumplimiento_max:
                raise ValidationError(_("El cumplimiento mínimo debe ser menor al máximo."))
            
            # Verificar solapamiento con otras líneas del mismo esquema.
            # Los intervalos son semiabiertos [min, max), por lo que dos rangos
            # se solapan si y solo si: min_A < max_B  AND  max_A > min_B
            overlapping = self.search([
                ('esquema_id', '=', record.esquema_id.id),
                ('id', '!=', record.id),
                ('cumplimiento_min', '<', record.cumplimiento_max),
                ('cumplimiento_max', '>', record.cumplimiento_min),
            ])
            if overlapping:
                raise ValidationError(_("Los rangos de cumplimiento no pueden solaparse."))
