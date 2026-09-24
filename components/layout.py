from contextlib import contextmanager
from nicegui import ui
from theme import apply_theme
from components.sidebar import Sidebar
from components.header import Header
from components.admin_voice_assistant import AdminVoiceAssistant
from services.users_service import can_any, context_labels, home_route


@contextmanager
def PageLayout(active,title,subtitle,eyebrow=None):
    apply_theme()
    ui.page_title(f'{title} · NEXO')
    drawer = Sidebar(active)
    Header(drawer)
    AdminVoiceAssistant()  # single instance for every page; hidden for non-administrators
    with ui.element('div').classes('page-heading'):
        with ui.column().classes('gap-0'):
            ui.label(eyebrow or context_labels()[1]).classes('eyebrow')
            ui.label(title).mark('page-title').props('role=heading aria-level=1').classes('text-[25px] font-medium tracking-tight')
            ui.label(subtitle).classes('subtitle mt-1')
        with ui.row().classes('items-center gap-2'):
            ui.icon('verified_user',size='15px',color='blue-grey-5')
            ui.label('Operación supervisada').classes('text-[10px] muted')
    yield
    with ui.element('div').classes('footer-line'):
        ui.label('NEXO / Uso institucional · Información de demostración')
        ui.label('Toda detección requiere revisión humana · v0.1')


def guard_page(active,*permissions):
    """Single gate for every route. Hiding a link is not access control: a page whose
    permission the session lacks is not rendered at all, however it was reached."""
    if can_any(*permissions):
        return True
    with PageLayout(active,'Acceso restringido',
                    'Tu rol no tiene permiso para consultar esta sección.'):
        with ui.element('section').classes('panel'):
            with ui.column().classes('panel-body items-start gap-3 p-6'):
                ui.icon('lock_outline',size='30px',color='blue-grey-4')
                ui.label('Esta sección pertenece a otra responsabilidad dentro de NEXO. '
                         'Cada rol trabaja únicamente con sus propias herramientas.').classes('text-sm')
                ui.button('Volver',icon='arrow_back',
                          on_click=lambda:ui.navigate.to(home_route())).props('unelevated no-caps')
    return False


@contextmanager
def Panel(title,subtitle=None):
    with ui.element('section').classes('panel'):
        with ui.element('div').classes('panel-heading'):
            ui.label(title).classes('section-title')
            if subtitle:
                ui.label(subtitle).classes('text-[10px] muted')
        yield


def notify_action(action,message,refresh=None):
    try:
        result = action()
        ui.notify(message,type='positive',position='bottom-right',timeout=2500)
        if refresh:
            refresh()
        return result
    except (ValueError,PermissionError) as error:
        ui.notify(str(error),type='warning',position='bottom-right')
    except ConnectionError:
        ui.notify('No fue posible conectar con el servicio. Intenta nuevamente.',type='negative')
