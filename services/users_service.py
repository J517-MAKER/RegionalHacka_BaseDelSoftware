from nicegui import app
from services import store

# Separation of duties: detecting, reviewing and authorising a deletion are different rights.
OPERATOR = {'case', 'review', 'track', 'voice', 'deletion.request'}
SUPERVISOR = OPERATOR | {'settings', 'deletion.approve'}
PERMISSIONS = {'Operador': OPERATOR,
               'Supervisor': SUPERVISOR,
               'Administrador': SUPERVISOR | {'users', 'audit', 'assistant'}}


def get_users():
    return store.users


def get_current_user():
    user_id = app.storage.user.get('user_id', 'USR-01')
    return next(u for u in store.users if u.id == user_id)


def can(action):
    user = get_current_user()
    return user.status == 'Activo' and action in PERMISSIONS[user.role]


def require(action):
    if not can(action):
        raise PermissionError('El rol de esta sesión no permite esta operación.')
    return get_current_user().username


def switch_demo_user(user_id):
    user = next(u for u in store.users if u.id == user_id and u.status == 'Activo')
    app.storage.user['user_id'] = user.id
    app.storage.user['authenticated'] = False
    store.audit(user.username, 'Sesión', f'Sesión de demostración: {user.role}')


def update_user(user_id, role, status):
    actor = require('users')
    user = next(u for u in store.users if u.id == user_id)
    if user.id == get_current_user().id:
        raise ValueError('No puedes modificar tu propia sesión activa.')
    if role not in PERMISSIONS or status not in ('Activo','Suspendido'):
        raise ValueError('Rol o estado no válido.')
    user.role, user.status = role, status
    store.audit(actor, 'Permisos', f'Actualizó {user.username}: {role}, {status}')
