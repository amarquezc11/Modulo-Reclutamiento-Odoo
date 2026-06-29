# -*- coding: utf-8 -*-
{
    'name': 'AI Recruitment Advanced',
    'version': '1.0',
    'summary': """Análisis de CVs contrastado con la descripción del puesto usando Gemini 2.5 Flash.""",
    'author': 'Alberto Marquez',
    'website': '',
    'category': 'Human Resources/Recruitment',
    'depends': [
        'resume_ai_analysis',
        'hr_recruitment',
        'website_hr_recruitment'
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_job_views.xml',
        'views/hr_applicant_views.xml',
        'views/website_hr_recruitment_templates_xml_views.xml',
    ],
    'application': True,
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}