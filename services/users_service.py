"""Roles and authorisation.

Separation of duties: operating, supervising and administering are three different
jobs, not three levels of the same one. No role inherits another's permissions, so
an administrator cannot review evidence and a supervisor cannot start a camera.
"""
from nicegui import app
from services import store

# Daily operational work: detect, register, review at first level, escalate.
OPERATOR = {'monitor.view',
            'cases.view', 'cases.manage', 'cases.import',
            'cameras.view',
            'live.view', 'live.control',
            'matches.view', 'matches.review',
            'tracking.view', 'tracking.control',
            'alerts.view', 'alerts.review',
            'evidence.play', 'deletion.request',
            'voice.monitor',
            'history.operational'}

# Second-level review and authorisation. Consults operational pages, never drives them.
SUPERVISOR = {'supervision.view', 'supervision.review',
              'cases.view', 'cameras.view',
              'matches.view', 'matches.supervise',
              'tracking.view', 'alerts.view',
              'evidence.play', 'deletion.approve',
              'audit.operational'}

# Platform administration. Reads operational pages, never acts on the chain of custody.
ADMINISTRATOR = {'cases.view', 'cameras.view', 'matches.view', 'tracking.view', 'alerts.view',
                 'users.manage', 'settings.manage', 'audit.full', 'assistant.use'}

PERMISSIONS = {'Operador': OPERATOR, 'Supervisor': SUPERVISOR, 'Administrador': ADMINISTRATOR}

# Where each role starts, and how its context is named in the header and the page eyebrow.
ROLE_HOME = {'Operador': '/monitor', 'Supervisor': '/supervision', 'Administrador': '/users'}
ROLE_CONTEXT = {'Operador': ('Centro de operaciones / Región Centro', 'CENTRO DE OPERACIONES'),
                'Supervisor': ('Centro de supervisión / Región Centro', 'CENTRO DE SUPERVISIÓN'),
                'Administrador': ('Administración del sistema / Región Centro',
                                  'ADMINISTRACIÓN DEL SISTEMA')}


def get_users():
    return store.users


def get_current_user():
    user_id = app.storage.user.get('user_id', 'USR-01')
    return next(u for u in store.users if u.id == user_id)


def can(action):
    user = get_current_user()
    return user.status == 'Activo' and action in PERMISSIONS[user.role]


def can_any(*actions):
    return any(can(action) for action in actions)


def require(action):
    if not can(action):
        raise PermissionError('El rol de esta sesión no permite esta operación.')
    return get_current_user().username


def home_route():
    """Landing page of the signed-in role; '/' redirects here instead of always to /monitor."""
    return ROLE_HOME.get(get_current_user().role, '/monitor')


def context_labels():
    """Header title and page eyebrow for the signed-in role."""
    return ROLE_CONTEXT.get(get_current_user().role, ROLE_CONTEXT['Operador'])


def switch_demo_user(user_id):
    """Cambia de puesto y cierra lo que abrió el anterior.

    Un cambio de perfil es un relevo, no una pestaña más: la cámara y la escucha continua que
    encendió el operador no pueden seguir corriendo en la sesión del administrador, cuyo único
    dispositivo es el micrófono del asistente de voz, y sólo mientras se habla con él.
    """
    user = next(u for u in store.users if u.id == user_id and u.status == 'Activo')
    app.storage.user['user_id'] = user.id
    app.storage.user['authenticated'] = False
    from services.camera_monitor_service import monitor
    monitor.apply_role(user.role, user.username)
    store.audit(user.username, 'Sesión', f'Sesión de demostración: {user.role}')


def update_user(user_id, role, status):
    actor = require('users.manage')
    user = next(u for u in store.users if u.id == user_id)
    if user.id == get_current_user().id:
        raise ValueError('No puedes modificar tu propia sesión activa.')
    if role not in PERMISSIONS or status not in ('Activo','Suspendido'):
        raise ValueError('Rol o estado no válido.')
    user.role, user.status = role, status
    store.audit(actor, 'Permisos', f'Actualizó {user.username}: {role}, {status}')
