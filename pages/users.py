from dataclasses import asdict
from nicegui import ui
from components.layout import PageLayout,Panel,notify_action,guard_page
from services.users_service import get_users,get_current_user,can,update_user


@ui.page('/users')
def users_page():
    if not guard_page('/users', 'users.manage'):
        return
    with PageLayout('/users','Usuarios y permisos','Roles y sesiones de demostración. La autorización de cada acción se verifica en los servicios de Python.'):
        ui.label('Modo de demostración: el menú de cuenta permite cambiar de rol. No sustituye un proveedor de autenticación.').classes('notice')
        def edit(user_id):
            user=next(u for u in get_users() if u.id==user_id)
            with ui.dialog() as dialog,ui.card().classes('w-96 p-6'):
                ui.label(f'Permisos / {user.username}').classes('section-title')
                role=ui.select(['Administrador','Operador','Supervisor'],value=user.role,label='Rol').props('outlined dense').classes('w-full')
                status=ui.select(['Activo','Suspendido'],value=user.status,label='Estado').props('outlined dense').classes('w-full')
                def save():
                    def action():
                        update_user(user.id,role.value,status.value)
                        dialog.close()
                    notify_action(action,'Permisos actualizados.',table.refresh)
                with ui.row():
                    ui.button('Cancelar',on_click=dialog.close).props('flat no-caps')
                    ui.button('Guardar',on_click=save).props('unelevated no-caps')
            dialog.open()
        @ui.refreshable
        def table():
            columns=[{'name':key,'field':key,'label':label,'align':'left','sortable':True} for key,label in [('name','Nombre'),('username','Usuario'),('role','Rol'),('last_access','Último acceso'),('status','Estado')]]
            if can('users.manage'):
                columns.append({'name':'actions','field':'id','label':'Permisos','align':'left'})
            widget=ui.table(columns=columns,rows=[asdict(u) for u in get_users()],row_key='id').classes('w-full')
            if can('users.manage'):
                widget.add_slot('body-cell-actions','<q-td :props="props"><q-btn flat dense color="primary" no-caps label="Editar" @click="$parent.$emit(\'edit\', props.row.id)" /></q-td>')
                widget.on('edit',lambda e:edit(e.args))
        table()
        with Panel('Alcance de los roles'):
            ui.table(columns=[{'name':key,'field':key,'label':label,'align':'left'} for key,label in [('role','Rol'),('scope','Funciones autorizadas')]],rows=[
                {'role':'Operador','scope':'Monitoreo, casos e importación de alertas, cámaras, reconocimiento en vivo, '
                                            'revisión de coincidencias y evidencia, seguimiento, detección de auxilio e historial operativo.'},
                {'role':'Supervisor','scope':'Bandeja de supervisión: resuelve lo escalado por operadores, autoriza o rechaza '
                                              'solicitudes de eliminación y consulta la auditoría operativa. No opera cámaras ni registra casos.'},
                {'role':'Administrador','scope':'Usuarios y permisos, configuración global, auditoría completa y Asistente NEXO. '
                                                 'Consulta las páginas operativas en modo lectura.'}],row_key='role').classes('w-full')
