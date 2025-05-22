# models/migrations.py
import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

def migrate_old_material_reservation_stages(cr, registry):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Stage = env['material.reservation.stage']
    Project = env['project.project']

    _logger.warning("🔄 Iniciando migración de etapas antiguas sin project_id")
    count = 0
    for stage in Stage.search([()]):
        obra_nr = str(stage.project_number or '')
        project = Project.search([('obra_nr', '=', obra_nr)], limit=1)
        if project:
            stage.project_id = project.id
            _logger.info(f"   • Etapa {stage.id} asociada a proyecto {project.id}")
        else:
            stage.project_id=20000
            _logger.warning(f"   • No se encontró proyecto para obra_nr={obra_nr} en etapa {stage.id}")
        count += 1
    _logger.warning(f"✅ Migración completada: procesadas {count} etapas")
