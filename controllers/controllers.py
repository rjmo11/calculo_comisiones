# -*- coding: utf-8 -*-
# from odoo import http


# class CalculoComisiones(http.Controller):
#     @http.route('/calculo_comisiones/calculo_comisiones', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/calculo_comisiones/calculo_comisiones/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('calculo_comisiones.listing', {
#             'root': '/calculo_comisiones/calculo_comisiones',
#             'objects': http.request.env['calculo_comisiones.calculo_comisiones'].search([]),
#         })

#     @http.route('/calculo_comisiones/calculo_comisiones/objects/<model("calculo_comisiones.calculo_comisiones"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('calculo_comisiones.object', {
#             'object': obj
#         })

