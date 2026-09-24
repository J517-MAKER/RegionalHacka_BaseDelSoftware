from datetime import datetime
from nicegui import ui
from services.live_recognition_service import live
from services.users_service import get_current_user, get_users, switch_demo_user


def Header(drawer):
    user = get_current_user()
    with ui.header().classes('topbar items-center flex-row gap-4'):
        ui.button(icon='menu',on_click=drawer.toggle).props('flat dense round aria-label="Abrir navegación"').classes('drawer-toggle')
        ui.label('Centro de operaciones / Región Centro').classes('topbar-title')
        ui.space()
        with ui.row().classes('items-center gap-2 header-connection'):
            ui.element('span').classes('status-dot text-[#357358]')
            ui.label('Servicios simulados conectados').classes('text-[10px] muted')
        # Visible on every page while the webcam is on, so it is never left running unnoticed.
        with ui.link(target='/live').classes('no-underline').bind_visibility_from(live, 'running'):
            with ui.row().classes('items-center gap-1'):
                ui.element('span').classes('status-dot').style('background:#c62828')
                ui.label('CÁMARA EN VIVO').classes('text-[10px] font-medium text-[#c62828]')
        clock = ui.label(datetime.now().strftime('%H:%M:%S')).classes('mono mx-3')
        ui.timer(1,lambda:clock.set_text(datetime.now().strftime('%H:%M:%S')))
        with ui.button().props('flat no-caps').classes('text-left'):
            with ui.row().classes('items-center gap-2'):
                with ui.avatar(color='blue-grey-1',text_color='blue-grey-8',size='30px'):
                    ui.label(''.join(word[0] for word in user.name.split()[:2])).classes('text-xs')
                with ui.column().classes('gap-0'):
                    ui.label(user.username).classes('text-[11px]')
                    ui.label(user.role+' · sesión activa').classes('text-[9px] muted')
                ui.icon('expand_more',size='16px')
            with ui.menu():
                ui.label('Cambiar sesión de prueba').classes('text-xs muted p-3')
                for account in get_users():
                    if account.status=='Activo':
                        def switch(uid=account.id):
                            switch_demo_user(uid)
                            ui.navigate.reload()
                        ui.menu_item(f'{account.username} · {account.role}',on_click=switch)
                ui.separator()
                ui.label('Demo sin autenticación real').classes('text-xs muted p-3')
