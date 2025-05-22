from odoo import api, SUPERUSER_ID, _
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    # Sólo correr si venimos de una versión anterior
    if not installed_version or installed_version < '1.2':
        env = api.Environment(cr, SUPERUSER_ID, {})
        Stage   = env['material.reservation.stage']
        Project = env['project.project']
        _logger.warning("🔄 Iniciando migración de etapas antiguas…")
        for stage in Stage.search([('project_id', '=', False)]):
            obra_nr = str(stage.project_number or '')
            project = Project.search([('obra_nr', '=', obra_nr)], limit=1)
            if project:
                stage.project_id = project.id
                _logger.info(f"  • Stage {stage.id} vinculado a proyecto {project.id}")
            else:
                _logger.warning(f"No se encontró proyecto para obra_nr={obra_nr} (stage {stage.id})")
        Stage._compute_project_number()
        _logger.warning("✅ Migración completada")
    else:
        _logger.info(f"Salto migración: ya está en versión {installed_version} o superior")

