"""Audit log, served at the level of detail each responsibility needs.

The filtering happens here and not in the table, so a role never receives entries it is
not entitled to read, whatever the interface asks for.
"""
from services import store
from services.users_service import can

# What an operator needs to follow their own work: detections, reviews and their evidence.
OPERATIONAL_KINDS = {'Búsqueda', 'Coincidencia', 'Revisión', 'Seguimiento', 'Voz',
                     'Alerta', 'Cámara', 'Importación', 'Evidencia'}
# A supervisor audits the same operational chain, including deletions and their resolution.
SUPERVISION_KINDS = OPERATIONAL_KINDS
# An administrator sees every category, including sessions, permissions and configuration.

SCOPES = {'operational': OPERATIONAL_KINDS, 'supervision': SUPERVISION_KINDS, 'full': None}
SCOPE_TITLES = {'operational': ('Historial operativo',
                                'Acciones, detecciones y revisiones de la operación. Cada decisión conserva '
                                'al usuario responsable.'),
                'supervision': ('Auditoría operativa',
                                'Actuaciones de los operadores, revisiones, evidencia y solicitudes de '
                                'eliminación con su resolución.'),
                'full': ('Auditoría completa',
                         'Bitácora íntegra del sistema: sesiones, permisos, configuración y toda la '
                         'actividad operativa.')}


def current_scope():
    """The widest scope the signed-in role is entitled to."""
    if can('audit.full'):
        return 'full'
    if can('audit.operational'):
        return 'supervision'
    return 'operational'


def get_history(scope='operational'):
    kinds = SCOPES.get(scope, OPERATIONAL_KINDS)
    records = sorted(store.logs, key=lambda item: item.timestamp, reverse=True)
    if kinds is None:
        return records
    return [r for r in records if r.kind in kinds]
