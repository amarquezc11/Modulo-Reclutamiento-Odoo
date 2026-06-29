# -*- coding: utf-8 -*-
import json
import logging
from odoo import models, api
from odoo.tools import html2plaintext

try:
    from google import genai
except ImportError:
    genai = None

_logger = logging.getLogger(__name__)

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    @api.model_create_multi
    def create(self, vals_list):
        # Crear los adjuntos utilizando el método original de Odoo
        attachments = super().create(vals_list)

        for attachment in attachments:
            # Comprobar que sea un archivo adjunto de un candidato y sea formato PDF con un ID de registro válido
            if (
                attachment.res_model == 'hr.applicant'
                and attachment.res_id
                and isinstance(attachment.res_id, int)
                and attachment.mimetype == 'application/pdf'
            ):
                _logger.info('PDF detectado para applicant ID: %s', attachment.res_id)
                self._procesar_evaluacion_ia(attachment)

        return attachments

    def write(self, vals):
        # Ejecutar escritura normal
        res = super().write(vals)

        # Si se actualizan campos clave de relación o datos del adjunto
        if 'res_model' in vals or 'res_id' in vals or 'datas' in vals:
            for attachment in self:
                if (
                    attachment.res_model == 'hr.applicant'
                    and attachment.res_id
                    and isinstance(attachment.res_id, int)
                    and attachment.mimetype == 'application/pdf'
                ):
                    _logger.info('PDF detectado en write para applicant ID: %s', attachment.res_id)
                    self._procesar_evaluacion_ia(attachment)
        return res

    def _procesar_evaluacion_ia(self, attachment):
        applicant = self.env['hr.applicant'].browse(attachment.res_id)
        
        if not applicant.exists():
            _logger.warning('No se encontró el candidato con ID: %s', attachment.res_id)
            return

        duplicate_reasons = applicant._get_duplicate_reasons()
        if duplicate_reasons:
            message = 'Registro duplicado'
            if duplicate_reasons:
                message += ': ' + ', '.join(duplicate_reasons)
            applicant.write({
                'ai_analysis_status': 'failed',
                'ai_error_msg': message
            })
            _logger.info('Applicant ID %s marcado como duplicado: %s', applicant.id, message)
            return

        if applicant.resume_cv_id and applicant.ai_analysis_status == 'done':
            _logger.info('El candidato ID %s ya tiene un CV con análisis completado. Omitiendo.', applicant.id)
            return

        try:
            applicant.write({
                'ai_analysis_status': 'processing',
                'ai_error_msg': False
            })
            
            resume_cv = self.env['resume.cv'].create({
                'file': attachment.datas,
                'file_name': attachment.name,
                'area': 'otros',
            })

            applicant.write({'resume_cv_id': resume_cv.id})

            if not resume_cv.texto:
                _logger.warning('No se extrajo texto del archivo PDF del CV ID %s.', resume_cv.id)
                applicant.write({
                    'ai_analysis_status': 'failed',
                    'ai_error_msg': 'No se pudo extraer texto del archivo PDF. Verifique que no sea una imagen escaneada o esté protegido.'
                })
                return

            if not genai:
                _logger.error('La librería google-genai no está instalada.')
                applicant.write({
                    'ai_analysis_status': 'failed',
                    'ai_error_msg': 'La librería google-genai no está instalada en el servidor de Odoo.'
                })
                return

            api_key = self.env['ir.config_parameter'].sudo().get_param('gemini_api_key')
            if not api_key:
                applicant.write({
                    'ai_analysis_status': 'failed',
                    'ai_error_msg': 'La clave de API de Gemini (gemini_api_key) no está configurada.'
                })
                return

            job_name = applicant.job_id.name or "Puesto no especificado"
            job_desc = applicant.job_id.description or ""

            job_desc_clean = ""
            if job_desc:
                try:
                    job_desc_clean = html2plaintext(job_desc).strip()
                except Exception:
                    job_desc_clean = job_desc
            else:
                job_desc_clean = "No se proporcionó una descripción para este puesto en Odoo."

            prompt = (
                "Eres un reclutador experto y asistente de recursos humanos inteligente.\n"
                "Tu tarea es evaluar detalladamente el Currículum Vitae (CV) de un candidato "
                "y compararlo minuciosamente con el puesto de trabajo al que aplica.\n\n"
                "=== PUESTO DE TRABAJO ===\n"
                f"Título: {job_name}\n"
                f"Descripción y Requisitos:\n{job_desc_clean}\n\n"
                "=== TEXTO EXTRAÍDO DEL CV DEL CANDIDATO ===\n"
                f"{resume_cv.texto}\n\n"
                "Analiza las modificaciones y brechas entre el perfil del candidato y el puesto. "
                "Debes responder ÚNICAMENTE con un objeto JSON válido con los siguientes campos y estructura:\n"
                "{\n"
                "  \"score\": (número entero entre 0 y 100 que represente el porcentaje de adecuación del candidato al puesto),\n"
                "  \"soft_skills\": (lista de strings con las habilidades blandas detectadas en el CV, ej. [\"Liderazgo\", \"Trabajo en equipo\"]),\n"
                "  \"languages\": (lista de strings con los idiomas detectados en el CV, ej. [\"Español\", \"Inglés\"])\n"
                "}\n\n"
                "Reglas estrictas:\n"
                "1. Responde solo con el JSON. Sin introducciones, sin explicaciones ni markdown.\n"
                "2. Escribe los textos en español de forma profesional.\n"
            )
            import time
            max_retries = 3
            backoff = 2
            response = None
            client = genai.Client(api_key=api_key)
            
            for attempt in range(max_retries):
                try:
                    _logger.info('Solicitando análisis a Gemini para applicant ID %s (intento %s)...', applicant.id, attempt + 1)
                    response = client.models.generate_content(
                        model='gemini-2.5-flash',
                        contents=prompt,
                        config={
                            'temperature': 0.2,
                            'response_mime_type': 'application/json',
                        }
                    )
                    break
                except Exception as e:
                    err_msg = str(e)
                    if attempt < max_retries - 1 and ("503" in err_msg or "UNAVAILABLE" in err_msg or "ResourceExhausted" in err_msg or "demand" in err_msg):
                        _logger.warning('Gemini temporalmente no disponible (503/UNAVAILABLE). Reintentando en %s segundos...', backoff)
                        time.sleep(backoff)
                        backoff *= 2
                    else:
                        raise e

            response_text = response.text.strip() if response.text else ''
            if not response_text:
                raise ValueError('La respuesta del modelo Gemini está vacía.')

            if response_text.startswith('```'):
                lines = response_text.splitlines()
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines and lines[-1].startswith('```'):
                    lines = lines[:-1]
                response_text = '\n'.join(lines).strip()

            data = json.loads(response_text)
            score = int(data.get('score', 0))
            soft_skills = data.get('soft_skills', [])
            languages = data.get('languages', [])

            if score == 0: priority_val = '0'
            elif score <= 20: priority_val = '1'
            elif score <= 40: priority_val = '2'
            elif score <= 60: priority_val = '3'
            elif score <= 80: priority_val = '4'
            else: priority_val = '5'

            # 1. Definimos los valores base de campos calculados por la IA
            vals_to_update = {
                'ai_score': score,
                'priority': priority_val,
                'ai_analysis_status': 'done',
                'ai_error_msg': False
            }

            # =================================================================
            # ASIGNACIÓN AUTOMÁTICA DIRECTA POR ID DE ETAPA (hr.recruitment.stage)
            # =================================================================
            # Asignamos el ID de base de datos correspondiente según el rango de nota
            if score <= 40:
                target_stage_id = 1  # Nuevo aspirante (ID de base de datos)
            elif score <= 65:
                target_stage_id = 2  # Llamada de aproximación (ID de base de datos)
            elif score <= 85:
                target_stage_id = 3  # Llamada de conocimientos técnicos (ID de base de datos)
            else:
                target_stage_id = 4  # Entrevista técnica (ID de base de datos)

            # Verificación preventiva: Nos aseguramos de que ese ID de etapa exista en este Odoo
            stage_exists = self.env['hr.recruitment.stage'].sudo().browse(target_stage_id).exists()
            
            if stage_exists:
                vals_to_update['stage_id'] = target_stage_id
                _logger.info('IA determinó mover al candidato %s directamente al stage_id físico: %s', applicant.id, target_stage_id)
            else:
                _logger.warning('La etapa con ID %s no existe en la tabla hr.recruitment.stage de esta base de datos.', target_stage_id)
            # =================================================================

            # Ejecutamos un único write al Candidato conteniendo tanto la data IA como el stage_id
            applicant.write(vals_to_update)
            _logger.info('Calificación y enrutamiento completado con éxito para el applicant ID %s.', applicant.id)

            # =================================================================
            # REGISTRO DE HABILIDADES Y IDIOMAS (TRY-EXCEPT PROTEGIDO)
            # =================================================================
            try:
                # En Odoo 18, hr.applicant está relacionado con hr.candidate (generalmente a través de candidate_id)
                candidate = applicant.candidate_id if hasattr(applicant, 'candidate_id') else False
                if candidate:
                    self._registrar_habilidades_candidato(candidate, soft_skills, languages)
                else:
                    _logger.warning('No se pudo registrar habilidades: el candidato (candidate_id) no está presente en el applicant %s.', applicant.id)
            except Exception as eskill:
                _logger.error('Error al registrar habilidades del candidato para el applicant %s: %s', applicant.id, str(eskill))
            # =================================================================

        except Exception as e:
            _logger.error('Error al calificar el CV del applicant %s con Gemini: %s', applicant.id, str(e))
            applicant.write({
                'ai_analysis_status': 'failed',
                'ai_error_msg': f'Error en el análisis de IA o asignación de etapa: {str(e)}'
            })

        return attachment

    def _registrar_habilidades_candidato(self, candidate, soft_skills, languages):
        if not candidate:
            return

        categorias = {
            'Habilidades Blandas': soft_skills,
            'Idiomas': languages
        }

        for tipo_nombre, skills_list in categorias.items():
            if not skills_list:
                continue

            # Buscar o crear el tipo de habilidad (hr.skill.type)
            skill_type = self.env['hr.skill.type'].sudo().search([('name', '=ilike', tipo_nombre)], limit=1)
            if not skill_type:
                skill_type = self.env['hr.skill.type'].sudo().create({'name': tipo_nombre})

            # Asegurarnos de que el tipo de habilidad tenga al menos un nivel (hr.skill.level)
            skill_level = self.env['hr.skill.level'].sudo().search([('skill_type_id', '=', skill_type.id)], order='level_progress desc', limit=1)
            if not skill_level:
                skill_level = self.env['hr.skill.level'].sudo().create({
                    'name': 'Intermedio',
                    'level_progress': 50,
                    'skill_type_id': skill_type.id
                })

            for skill_name in skills_list:
                skill_name = skill_name.strip()
                if not skill_name:
                    continue

                # Buscar o crear la habilidad (hr.skill)
                skill = self.env['hr.skill'].sudo().search([
                    ('name', '=ilike', skill_name),
                    ('skill_type_id', '=', skill_type.id)
                ], limit=1)
                if not skill:
                    skill = self.env['hr.skill'].sudo().create({
                        'name': skill_name,
                        'skill_type_id': skill_type.id
                    })

                # Verificar si el candidato ya tiene esta habilidad registrada en candidate_skill_ids
                # En Odoo 18, las habilidades del candidato se vinculan a través de hr.candidate.skill
                existe = self.env['hr.candidate.skill'].sudo().search([
                    ('candidate_id', '=', candidate.id),
                    ('skill_id', '=', skill.id)
                ], limit=1)

                if not existe:
                    self.env['hr.candidate.skill'].sudo().create({
                        'candidate_id': candidate.id,
                        'skill_id': skill.id,
                        'skill_type_id': skill_type.id,
                        'skill_level_id': skill_level.id
                    })
                    _logger.info('Registrada habilidad "%s" para el candidato %s', skill_name, candidate.id)