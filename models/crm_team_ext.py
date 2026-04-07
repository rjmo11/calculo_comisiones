# -*- coding: utf-8 -*-
from odoo import models, fields

class CrmTeam(models.Model):
    _inherit = 'crm.team'

    team_type = fields.Selection([
        ('masivo', 'Consumo Masivo'),
        ('profesional', 'Consumo Profesional'),
        ('especial', 'Ventas Especiales')
    ], string='Tipo de Departamento', default='masivo', required=True)
