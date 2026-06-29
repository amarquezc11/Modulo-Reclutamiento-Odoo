# -*- coding: utf-8 -*-
import logging
import re

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# 1. DEFINIR LAS NUEVAS OPCIONES COMPARTIDAS
# Las extraemos a una variable para asegurar que ambos modelos usen exactamente lo mismo
NUEVA_PRIORIDAD_SELECTION = [
    ('0', 'Sin Calificar'),
    ('1', 'Malo'),
    ('2', 'Regular'),
    ('3', 'Bueno'),
    ('4', 'Muy Bueno'),
    ('5', 'Excelente')
]

class HrApplicant(models.Model):
    _inherit = 'hr.applicant'

    # Sobreescribimos en el Postulante
    priority = fields.Selection(NUEVA_PRIORIDAD_SELECTION, string='Prioridad', default='0')

    resume_cv_id = fields.Many2one(
        'resume.cv',
        string='CV / Hoja de Vida',
        help='Referencia al CV procesado'
    )
    ai_score = fields.Integer(
        string='Calificación de la IA',
        help='Calificación numérica (0-100) calculada por la IA comparando el CV con el puesto.'
    )
    ai_analysis_status = fields.Selection([
        ('draft', 'Sin Procesar'),
        ('processing', 'Procesando...'),
        ('done', 'Completado'),
        ('failed', 'Fallido'),
    ], string='Estado del Análisis', default='draft')
    
    ai_error_msg = fields.Text(
        string='Error de la IA',
        help='Mensaje de error en caso de que falle la evaluación de la IA.'
    )

    def _normalize_phone(self, phone):
        self.ensure_one()
        return re.sub(r"\D", "", (phone or '').strip())

    def _get_duplicate_reasons(self):
        self.ensure_one()

        reasons = []
        if self.email_from:
            if self.search_count([('id', '!=', self.id), ('email_from', '=ilike', self.email_from)]) > 0:
                reasons.append('correo')

        if self.partner_phone:
            phone_norm = self._normalize_phone(self.partner_phone)
            if phone_norm:
                duplicates = self.search([('id', '!=', self.id), ('partner_phone', '!=', False)])
                for rec in duplicates:
                    if self._normalize_phone(rec.partner_phone) == phone_norm:
                        reasons.append('teléfono')
                        break

        return reasons

    @api.model_create_multi
    def create(self, vals_list):
        """
        Filtro interno post-envío: Valida duplicados silenciosamente.
        Si detecta repetidos, frena la creación en la DB pero no rompe la web.
        """
        
        if isinstance(vals_list, dict):
            vals_list = [vals_list]

        valid_vals_list = []

        default_email = "admin@dereksb-tt-odoo-practicantes-utp.odoo.com"
        default_phone = "+5076885454"

        for vals in vals_list:
            name = vals.get('name', '').strip() if vals.get('name') else ''
            email = (vals.get('email_from') or vals.get('email') or '').strip()
            email_norm = email.lower() if email else ''
            phone = (vals.get('partner_phone') or vals.get('phone') or vals.get('mobile') or '').strip()
            phone_norm = re.sub(r"\D", "", phone) if phone else ''

            is_duplicate = False
            reasons = []

            if email_norm and email_norm != default_email.lower():
                if self.sudo().search_count([('email_from', '=ilike', email)]) > 0:
                    is_duplicate = True
                    reasons.append(f"Correo ({email})")

            if phone_norm and re.sub(r"\D", "", default_phone) != phone_norm:
                existing = self.sudo().search([('partner_phone', '!=', False)])
                for rec in existing:
                    rec_phone_norm = re.sub(r"\D", "", rec.partner_phone or '')
                    if rec_phone_norm and rec_phone_norm == phone_norm:
                        is_duplicate = True
                        reasons.append(f"Teléfono ({phone})")
                        break

            # 5. Evaluar si pasa el filtro o se descarta
            if is_duplicate:
                _logger.warning(
                    "=== POSTULACIÓN RECHAZADA POR DUPLICADO === Se intentó registrar a "
                    "'%s' pero ya existe en el sistema por: %s. No se creará el registro.", 
                    name or 'Desconocido', ", ".join(reasons)
                )
                # Al NO agregar 'vals' a 'valid_vals_list', este registro no se creará.
                continue
    
            valid_vals_list.append(vals)

        if not valid_vals_list:
            return self.browse()

        return super(HrApplicant, self).create(valid_vals_list)

    @api.model
    def website_form_input_filter(self, request, values):
        _logger.error('=== WEBSITE APPLY VALUES === %s', values)
        values = super(HrApplicant, self).website_form_input_filter(request, values)
        params = request.params or {}

        if params.get('medium_id'):
            try:
                values['medium_id'] = int(params['medium_id'])
            except (ValueError, TypeError):
                pass

        if params.get('source_id'):
            try:
                values['source_id'] = int(params['source_id'])
            except (ValueError, TypeError):
                pass

        if params.get('salary_expected'):
            try:
                values['salary_expected'] = float(params['salary_expected'])
            except (ValueError, TypeError):
                pass

        if params.get('availability'):
            values['availability'] = params['availability']

        if params.get('type_id'):
            try:
                values['type_id'] = int(params['type_id'])
            except (ValueError, TypeError):
                pass

        _logger.error('=== WEBSITE APPLY VALUES === %s', values)
        return values


class HrCandidate(models.Model):
    _inherit = 'hr.candidate'

    priority = fields.Selection(NUEVA_PRIORIDAD_SELECTION, string='Prioridad', default='0')