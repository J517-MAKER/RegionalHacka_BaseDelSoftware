from copy import deepcopy
from services import store
from services.users_service import require


def get_settings():
    return deepcopy(store.settings)


def save_settings(section, values):
    actor = require('settings')
    store.settings[section].update(values)
    store.audit(actor,'Configuración',f'Actualizó preferencias de {section}')
