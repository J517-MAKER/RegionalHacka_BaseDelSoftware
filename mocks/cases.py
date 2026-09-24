from models.person import Person
from models.search_case import SearchCase


def seed_cases():
    names = ['Elena Robles (ficticia)', 'Mateo Silva (ficticio)', 'Lucía Vega (ficticia)', 'Daniel Ríos (ficticio)']
    locations = ['Plaza de la República', 'Estación Alameda', 'Mercado del Centro', 'Parque Norte']
    return [SearchCase(
        id=f'BUS-2026-{184+i:04d}',
        person=Person(name=name, age=str(24+i*7), sex='No especificado', height='1.65 m',
                      build='Media', skin='No especificado', hair='Castaño', eyes='Café',
                      clothing='Chaqueta azul, pantalón oscuro y calzado blanco.',
                      marks='Sin señas particulares reportadas.', description='Registro ficticio para demostración.',
                      photos=[f'/assets/demo/person-{i+1}.svg']),
        missing_date=f'2026-09-{22-i:02d}', reported_at=f'2026-09-23 0{8+i//2}:15',
        location=locations[i], zone=['Centro', 'Centro', 'Poniente', 'Norte'][i],
        owner=['Operador01', 'Operador02'][i % 2], reference_status='Referencia procesada · simulación',
    ) for i, name in enumerate(names)]
