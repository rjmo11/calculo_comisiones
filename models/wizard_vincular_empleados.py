# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class WizardVincularEmpleados(models.TransientModel):
    """
    Wizard de vinculación automática:
      1. Crea hr.employee para cada usuario del equipo de ventas.
      2. Migra los datos existentes en meta.vendedor y calculo.comision
         cuyo vendedor_id todavía apunta a IDs de res.users.
    """
    _name = 'wizard.vincular.empleados'
    _description = 'Asistente de Vinculación Usuarios → Empleados'

    solo_equipos_crm = fields.Boolean(
        string='Solo miembros de equipos CRM',
        default=True,
        help=(
            "Activado: solo usuarios miembros/líderes de equipos CRM. "
            "Desactivado: todos los usuarios internos activos."
        )
    )
    resultado_texto = fields.Text(string='Resultado', readonly=True)
    ejecutado = fields.Boolean(default=False)

    # ------------------------------------------------------------------
    def action_vincular(self):
        """
        Paso 1 - Crea hr.employee para cada usuario candidato.
        Paso 2 - Migra vendedor_id en meta_vendedor y calculo_comision
                 para que apunte al hr.employee correcto en lugar del
                 res.users antiguo.
        """
        self.ensure_one()
        Employee = self.env['hr.employee'].sudo()
        log = []

        # Construir lista de usuarios candidatos
        if self.solo_equipos_crm:
            equipos = self.env['crm.team'].sudo().search([])
            uid_set = set(equipos.mapped('member_ids').ids)
            for eq in equipos:
                if eq.user_id:
                    uid_set.add(eq.user_id.id)
            usuarios = self.env['res.users'].sudo().browse(list(uid_set)).filtered(
                lambda u: u.active and not u.share
            )
        else:
            usuarios = self.env['res.users'].sudo().search([
                ('active', '=', True),
                ('share', '=', False),
            ])

        if not usuarios:
            raise UserError(_("No se encontraron usuarios que cumplan los criterios."))

        creados = []
        ya_existentes = []
        errores_paso1 = []

        # ── PASO 1: Crear empleados ─────────────────────────────────────
        for usuario in usuarios:
            try:
                emp = Employee.search([('user_id', '=', usuario.id)], limit=1)
                if emp:
                    ya_existentes.append("  - %s -> emp ID %s" % (usuario.name, emp.id))
                else:
                    nuevo = Employee.create({
                        'name': usuario.name,
                        'user_id': usuario.id,
                        'work_email': usuario.email or '',
                        'job_title': _('Vendedor'),
                        'company_id': usuario.company_id.id or self.env.company.id,
                    })
                    creados.append("  - %s -> emp ID %s" % (usuario.name, nuevo.id))
            except Exception as e:
                errores_paso1.append("  - %s: %s" % (usuario.name, e))

        log.append("=== PASO 1: Empleados creados (%s) ===" % len(creados))
        log += creados if creados else ["  (ninguno nuevo)"]
        log.append("  Ya vinculados: %s" % len(ya_existentes))
        log += ya_existentes if ya_existentes else ["  (ninguno)"]
        if errores_paso1:
            log.append("  Errores: %s" % len(errores_paso1))
            log += errores_paso1

        # ── PASO 2: Migrar datos existentes ─────────────────────────────
        # Mapa: res.users.id -> hr.employee.id
        user_to_emp = {
            emp.user_id.id: emp.id
            for emp in Employee.search([('user_id', '!=', False)])
        }

        migrados_meta = 0
        migrados_calculo = 0
        errores_paso2 = []

        # --- Migrar meta.vendedor ---
        self.env.cr.execute(
            "SELECT id, vendedor_id FROM meta_vendedor WHERE vendedor_id IS NOT NULL"
        )
        rows_meta = self.env.cr.fetchall()
        for row_id, old_id in rows_meta:
            # Si ya es un employee_id válido, no tocar
            if Employee.browse(old_id).exists():
                continue
            new_emp_id = user_to_emp.get(old_id)
            if new_emp_id:
                self.env.cr.execute(
                    "UPDATE meta_vendedor SET vendedor_id = %s WHERE id = %s",
                    (new_emp_id, row_id)
                )
                migrados_meta += 1
            else:
                # Sin empleado para ese user_id: limpiar para evitar error
                self.env.cr.execute(
                    "UPDATE meta_vendedor SET vendedor_id = NULL WHERE id = %s",
                    (row_id,)
                )
                errores_paso2.append(
                    "  meta.vendedor ID %s: user_id %s sin empleado -> limpiado" % (row_id, old_id)
                )

        # --- Migrar calculo.comision ---
        self.env.cr.execute(
            "SELECT id, vendedor_id FROM calculo_comision WHERE vendedor_id IS NOT NULL"
        )
        rows_calc = self.env.cr.fetchall()
        for row_id, old_id in rows_calc:
            if Employee.browse(old_id).exists():
                continue
            new_emp_id = user_to_emp.get(old_id)
            if new_emp_id:
                self.env.cr.execute(
                    "UPDATE calculo_comision SET vendedor_id = %s WHERE id = %s",
                    (new_emp_id, row_id)
                )
                migrados_calculo += 1
            else:
                self.env.cr.execute(
                    "UPDATE calculo_comision SET vendedor_id = NULL WHERE id = %s",
                    (row_id,)
                )
                errores_paso2.append(
                    "  calculo.comision ID %s: user_id %s sin empleado -> limpiado" % (row_id, old_id)
                )

        # Invalidar cache ORM
        self.env['meta.vendedor'].invalidate_model()
        self.env['calculo.comision'].invalidate_model()

        log.append("")
        log.append("=== PASO 2: Migracion de datos existentes ===")
        log.append("  meta.vendedor actualizados:    %s" % migrados_meta)
        log.append("  calculo.comision actualizados: %s" % migrados_calculo)
        if errores_paso2:
            log.append("  Advertencias:")
            log += errores_paso2

        self.write({
            'resultado_texto': "\n".join(log),
            'ejecutado': True,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': _('Resultado de Vinculacion y Migracion'),
        }
