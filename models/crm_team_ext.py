# -*- coding: utf-8 -*-
from odoo import models

class CrmTeam(models.Model):
    _inherit = 'crm.team'
    
    # Campo team_type eliminado para favorecer flexibilidad dinámica por equipos estándar.
