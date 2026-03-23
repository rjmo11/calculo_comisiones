# -*- coding: utf-8 -*-
from odoo.tests.common import TransactionCase
from odoo.fields import Date
from datetime import date
from odoo.exceptions import ValidationError

class TestComisionFlow(TransactionCase):

    def setUp(self):
        super(TestComisionFlow, self).setUp()
        
        # 1. Crear Vendedor de Prueba
        self.vendedor = self.env['res.users'].create({
            'name': 'Vendedor de Prueba',
            'login': 'vendedor_test',
            'email': 'vendedor@test.com',
            'groups_id': [
                (4, self.env.ref('base.group_user').id),
                (4, self.env.ref('account.group_account_invoice').id)
            ]
        })

        # 2. Crear Cliente
        self.cliente = self.env['res.partner'].create({
            'name': 'Cliente de Prueba',
            'is_company': True,
        })

        # 3. Crear Esquema de Comisión (100% cumplimiento = 100% bono)
        self.esquema = self.env['esquema.comision'].create({
            'nombre': 'Esquema Test 100%',
            'linea_escala_ids': [
                (0, 0, {
                    'cumplimiento_min': 0,
                    'cumplimiento_max': 50,
                    'factor_pago': 0  # 0% pago si < 50% cumplimiento
                }),
                (0, 0, {
                    'cumplimiento_min': 50,
                    'cumplimiento_max': 100,
                    'factor_pago': 80  # 80% pago
                }),
                (0, 0, {
                    'cumplimiento_min': 100,
                    'cumplimiento_max': 999,
                    'factor_pago': 100  # 100% pago
                })
            ]
        })

        # 4. Crear Meta del Vendedor para el mes actual
        hoy = date.today()
        self.meta = self.env['meta.vendedor'].create({
            'vendedor_id': self.vendedor.id,
            'esquema_id': self.esquema.id,
            'periodo_mes': str(hoy.month),
            'periodo_anio': hoy.year,
            'moneda_id': self.env.company.currency_id.id,
            'meta_venta': 1000.0,
            'meta_cobranza': 1000.0,
            'bono_base_venta': 100.0,
            'bono_base_cobranza': 100.0,
            'state': 'active'
        })

    def test_01_calculo_comision_completo(self):
        """ Prueba el flujo completo: Facturación -> Cobranza -> Cálculo """
        
        # --- Simulación de Facturación ---
        # Crear 5 facturas de 200 cada una (Total 1000 = 100% meta)
        facturas = self.env['account.move']
        for i in range(5):
            factura = self.env['account.move'].create({
                'move_type': 'out_invoice',
                'partner_id': self.cliente.id,
                'invoice_user_id': self.vendedor.id,
                'invoice_date': date.today(),
                'invoice_line_ids': [(0, 0, {
                    'name': 'Producto de Prueba',
                    'quantity': 1,
                    'price_unit': 200.0,
                    'tax_ids': [],
                })]
            })
            factura.action_post()
            facturas |= factura

        # --- Simulación de Cobranza ---
        # Registrar 3 pagos que sumen 1000 (Total 1000 = 100% meta)
        montos_pagos = [400.0, 300.0, 300.0]
        pagos = self.env['account.payment']
        facturas_list = list(facturas)
        
        for i, monto in enumerate(montos_pagos):
            pago = self.env['account.payment'].with_user(self.vendedor).create({
                'payment_type': 'inbound',
                'partner_type': 'customer',
                'partner_id': self.cliente.id,
                'amount': monto,
                'date': date.today(),
                'journal_id': self.env['account.journal'].search([('type', 'in', ('bank', 'cash')), ('company_id', '=', self.vendedor.company_id.id)], limit=1).id,
                'vendedor_id': self.vendedor.id,  # Nuevo campo explícito
            })
            pago.action_post()
            
            # Conciliar con una de las facturas para asegurar vínculo por reconciled_invoice_ids
            # Buscamos las líneas de cuenta por cobrar del pago y la factura (ampliamos tipos por seguridad)
            types = ('asset_receivable', 'receivable')
            lineas_pago = pago.move_id.line_ids.filtered(lambda l: l.account_id.account_type in types)
            lineas_factura = facturas_list[i].line_ids.filtered(lambda l: l.account_id.account_type in types)
            (lineas_pago + lineas_factura).reconcile()
            
            pagos |= pago

        # Asegurar que los cambios se guarden y procesen antes del cálculo
        self.env.flush_all()
        self.env.invalidate_all()

        # --- Ejecución del Cálculo ---
        hoy = date.today()
        primer_dia = hoy.replace(day=1)
        ultimo_dia = hoy  # Por simplicidad usamos hoy como fin
        
        calculo = self.env['calculo.comision'].create({
            'vendedor_id': self.vendedor.id,
            'meta_id': self.meta.id,
            'fecha_inicio': primer_dia,
            'fecha_fin': ultimo_dia,
        })
        
        calculo.action_procesar_calculo()

        # --- Validaciones ---
        # 1. Montos Reales
        self.assertEqual(calculo.venta_real_monto, 1000.0, "El monto de venta real no coincide")
        self.assertEqual(calculo.cobranza_real_monto, 1000.0, "El monto de cobranza real no coincide")
        
        # 2. Porcentajes (1000/1000 = 1.0)
        self.assertEqual(calculo.porcentaje_cumplimiento_v, 1.0, "El % de cumplimiento de venta debe ser 100% (1.0)")
        self.assertEqual(calculo.porcentaje_cumplimiento_c, 1.0, "El % de cumplimiento de cobranza debe ser 100% (1.0)")

        # 3. Bonos Logrados (Bono Base 100 * factor 100% = 100)
        self.assertEqual(calculo.monto_bono_venta, 100.0, "El bono de venta logrado es incorrecto")
        self.assertEqual(calculo.monto_bono_cobranza, 100.0, "El bono de cobranza logrado es incorrecto")
        self.assertEqual(calculo.total_a_pagar, 200.0, "El total a pagar es incorrecto")

    def test_02_restriccion_duplicados(self):
        """ Verifica que no se puedan crear cálculos solapados para el mismo vendedor """
        hoy = date.today()
        primer_dia = hoy.replace(day=1)
        
        # Crear el primer cálculo
        self.env['calculo.comision'].create({
            'vendedor_id': self.vendedor.id,
            'meta_id': self.meta.id,
            'fecha_inicio': primer_dia,
            'fecha_fin': hoy,
        })

        # Intentar crear un segundo cálculo para el mismo periodo
        with self.assertRaises(ValidationError):
            self.env['calculo.comision'].create({
                'vendedor_id': self.vendedor.id,
                'meta_id': self.meta.id,
                'fecha_inicio': primer_dia,
                'fecha_fin': hoy,
            })
