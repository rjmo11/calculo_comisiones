from odoo import models, fields, api, _
from odoo.exceptions import UserError

class ReporteHistoricoWizard(models.TransientModel):
    _name = 'wizard.reporte.historico.comisiones'
    _description = 'Wizard para Reporte Histórico de Comisiones'

    fecha_inicio = fields.Date(string='Fecha Desde', required=True)
    fecha_fin = fields.Date(string='Fecha Hasta', required=True)
    vendedor_ids = fields.Many2many('hr.employee', string='Vendedores a Incluir', domain=[('user_id', '!=', False)])
    
    def get_calculos(self):
        self.ensure_one()
        domain = [
            ('fecha_inicio', '>=', self.fecha_inicio),
            ('fecha_fin', '<=', self.fecha_fin),
            ('state', 'in', ['calculated', 'approved'])
        ]
        if self.vendedor_ids:
            domain.append(('vendedor_id', 'in', self.vendedor_ids.ids))

        return self.env['calculo.comision'].search(domain, order='vendedor_id, fecha_inicio asc')

    def action_generate_report(self):
        """Llama a la impresión del PDF basado en el propio wizard"""
        self.ensure_one()
        if self.fecha_inicio > self.fecha_fin:
            raise UserError(_("La fecha 'Desde' no puede ser mayor que la fecha 'Hasta'."))

        calculos = self.get_calculos()

        if not calculos:
            raise UserError(_("No se encontraron registros de comisiones calculadas en este rango para los vendedores seleccionados."))

        # Para el reporte, pasamos al wizard mismo como 'doc'
        return self.env.ref('calculo_comisiones.action_report_historico_comisiones').report_action(self)
