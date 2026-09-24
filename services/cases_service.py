import base64
from services import store
from services.users_service import require
from models.person import Person
from models.search_case import SearchCase


def get_cases():
    return store.cases


def get_active_cases():
    return [c for c in store.cases if c.status == 'En búsqueda']


def get_case(case_id):
    return next((c for c in store.cases if c.id == case_id), None)


def create_case(data):
    actor = require('cases.manage')
    name = str(data.get('name','')).strip()
    if not name:
        raise ValueError('Escribe el nombre o indica «Persona desconocida».')
    person_fields = {k: data.get(k) or 'Desconocido' for k in ('age','sex','height','build','skin','hair','eyes','clothing','marks','description')}
    person = Person(name=name, **person_fields, photos=list(data.get('photos',[])))
    number = max(int(c.id.rsplit('-',1)[1]) for c in store.cases)+1
    case = SearchCase(f'BUS-2026-{number:04d}', person, data.get('missing_date') or 'Desconocida', store.now(),
                      data.get('location') or 'Desconocida', data.get('zone') or 'Sin zona', actor,
                      missing_time=data.get('missing_time') or 'Desconocida',
                      reference_status='Referencia fotográfica registrada' if person.photos else 'Sin referencia fotográfica')
    store.cases.append(case)
    store.audit(actor,'Búsqueda','Registró caso y solicitó procesamiento simulado',case.id)
    return case


def photo_data_url(content, content_type):
    if content_type not in ('image/png','image/jpeg','image/webp') or len(content)>5*1024*1024:
        raise ValueError('Utiliza imágenes PNG, JPG o WebP de hasta 5 MB.')
    if not (content.startswith(b'\x89PNG') or content.startswith(b'\xff\xd8\xff') or (content[:4]==b'RIFF' and content[8:12]==b'WEBP')):
        raise ValueError('El archivo no contiene una imagen compatible.')
    return f'data:{content_type};base64,{base64.b64encode(content).decode()}'


def add_case_photo(case_id,content,content_type):
    actor=require('cases.manage')
    case=get_case(case_id)
    if not case:
        raise ValueError('No se encontró este expediente.')
    if len(case.person.photos)>=5:
        raise ValueError('Máximo cinco fotografías por caso.')
    case.person.photos.append(photo_data_url(content,content_type))
    case.reference_status='Referencia fotográfica registrada'
    store.audit(actor,'Búsqueda','Añadió fotografía de referencia de prueba',case_id)
