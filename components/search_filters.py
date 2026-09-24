from nicegui import ui


def SearchFilters(on_change,statuses=None,zones=None,owners=None,with_date=False):
    fields={}
    with ui.element('div').classes('toolbar'):
        fields['query']=ui.input('Buscar nombre o folio',on_change=on_change).props('outlined dense clearable').classes('min-w-[230px]')
        if statuses:
            fields['status']=ui.select(['Todos']+statuses,value='Todos',label='Estado',on_change=on_change).props('outlined dense')
        if zones:
            fields['zone']=ui.select(['Todas']+zones,value='Todas',label='Zona',on_change=on_change).props('outlined dense')
        if owners:
            fields['owner']=ui.select(['Todos']+owners,value='Todos',label='Responsable',on_change=on_change).props('outlined dense')
        if with_date:
            fields['date']=ui.input('Fecha del reporte',on_change=on_change).props('outlined dense type=date clearable stack-label')
    return fields
