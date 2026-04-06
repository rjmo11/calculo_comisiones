# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request
import io
import xlsxwriter
import datetime

class CalculoComisionExcelController(http.Controller):

    @http.route('/calculo_comisiones/export_xlsx', type='http', auth='user')
    def export_calculo_xlsx(self, ids, **kw):
        # Convertir ids (str) a lista de enteros
        record_ids = [int(i) for i in ids.split(',') if i.isdigit()]
        if not record_ids:
            return request.not_found()

        # Al usar request.env las Record Rules aplican automáticamente
        calculos = request.env['calculo.comision'].browse(record_ids)
        if not calculos:
            return request.not_found()

        # Setup del archivo de Excel
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet('Liquidaciones')

        # Formatos
        header_format = workbook.add_format({
            'bold': True, 'bg_color': '#D3D3D3', 'border': 1, 'align': 'center', 'valign': 'vcenter'
        })
        text_format = workbook.add_format({'border': 1})
        money_format = workbook.add_format({'border': 1, 'num_format': '#,##0.00'})
        percent_format = workbook.add_format({'border': 1, 'num_format': '0.00%'})

        # Columnas solicitadas:
        # Nombre, Cédula (Vat), Meta Venta, Logro Venta, % Venta, Meta Cobro, Logro Cobro, % Cobro, Total a Pagar
        headers = [
            'Referencia', 'Nombre del Vendedor', 'Cédula / RIF', 
            'Meta de Venta', 'Logro de Venta', '% Cumplimiento Venta',
            'Meta de Cobranza', 'Logro de Cobranza', '% Cumplimiento Cobranza',
            'Monto Total a Pagar'
        ]

        # Ancho de columnas aproximado
        worksheet.set_column('A:A', 15)
        worksheet.set_column('B:B', 30)
        worksheet.set_column('C:C', 15)
        worksheet.set_column('D:E', 18)
        worksheet.set_column('F:F', 20)
        worksheet.set_column('G:H', 18)
        worksheet.set_column('I:I', 20)
        worksheet.set_column('J:J', 20)

        for col_num, header in enumerate(headers):
            worksheet.write(0, col_num, header, header_format)

        row = 1
        for calculo in calculos:
            vat = calculo.vendedor_id.partner_id.vat or ''
            
            worksheet.write(row, 0, calculo.name, text_format)
            worksheet.write(row, 1, calculo.vendedor_id.name, text_format)
            worksheet.write(row, 2, vat, text_format)
            
            worksheet.write_number(row, 3, calculo.meta_venta, money_format)
            worksheet.write_number(row, 4, calculo.venta_real_monto, money_format)
            worksheet.write_number(row, 5, calculo.porcentaje_cumplimiento_v, percent_format)
            
            worksheet.write_number(row, 6, calculo.meta_cobranza, money_format)
            worksheet.write_number(row, 7, calculo.cobranza_real_monto, money_format)
            worksheet.write_number(row, 8, calculo.porcentaje_cumplimiento_c, percent_format)
            
            worksheet.write_number(row, 9, calculo.total_a_pagar, money_format)
            row += 1

        workbook.close()
        output.seek(0)
        
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = "Reporte_Maestro_Liquidacion_%s.xlsx" % timestamp

        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename=%s;' % filename)
            ]
        )
