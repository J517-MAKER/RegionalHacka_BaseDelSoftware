from nicegui import ui
from components.status_badge import StatusBadge


def InfoPair(label,value):
    with ui.element('div').classes('info-pair'):
        ui.label(label).classes('label')
        ui.label(str(value)).classes('value')


def PersonProfile(case):
    with ui.element('section').classes('panel'):
        photo=ui.image(case.person.photos[0] if case.person.photos else '/assets/demo/person-1.svg').classes('profile-photo').props('fit=contain')
        with ui.column().classes('panel-body gap-2'):
            if len(case.person.photos)>1:
                with ui.row():
                    for source in case.person.photos:
                        ui.image(source).classes('w-12 h-14 cursor-pointer').on('click',lambda s=source:photo.set_source(s))
            ui.label(case.id).classes('mono muted')
            ui.label(case.person.name).classes('text-lg font-medium')
            StatusBadge(case.status)
            for label,value in [('Edad',case.person.age),('Desaparición',case.missing_date+' · '+case.missing_time),
                                 ('Fecha del reporte',case.reported_at),('Última ubicación',case.location),
                                 ('Características',f'{case.person.height} · Complexión {case.person.build} · Cabello {case.person.hair} · Ojos {case.person.eyes}'),
                                 ('Vestimenta',case.person.clothing),('Señas particulares',case.person.marks),('Información adicional',case.person.description)]:
                InfoPair(label,value)
            ui.label('PROCESAMIENTO FACIAL').classes('eyebrow mt-4')
            ui.label(case.reference_status).classes('text-xs')
            ui.label(f'Fotografías de referencia: {len(case.person.photos)}').classes('text-xs muted')
            ui.label('Huella facial: InsightFace la calcula al comparar fichas importadas.').classes('text-[10px] muted')
