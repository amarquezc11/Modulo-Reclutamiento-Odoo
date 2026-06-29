# -*- coding: utf-8 -*-
from odoo import models, fields, api

class HrJob(models.Model):
    _inherit = 'hr.job'
    top_candidates_count = fields.Integer(
        string="Cantidad de Top Postulantes a mostrar", 
        default=5,
        help="Número de postulantes que se mostrarán en el Top, ordenados por su calificación de IA."
    )
    
    top_applicant_ids = fields.One2many(
        'hr.applicant',
        'job_id',
        compute='_compute_top_applicants',
        string="Top Postulantes"
    )
    @api.depends('top_candidates_count')
    def _compute_top_applicants(self):
        for job in self:
            if job.top_candidates_count > 0:
                top_applicants = self.env['hr.applicant'].search([
                    ('job_id', '=', job.id),
                    ('ai_score', '>', 0)
                ], order='ai_score DESC', limit=job.top_candidates_count)
                job.top_applicant_ids = top_applicants
            else:
                job.top_applicant_ids = self.env['hr.applicant']