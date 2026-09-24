"""Consulta rápida de la base de datos de NEXO desde la terminal.

Uso (con el entorno virtual):
    .venv\\Scripts\\python.exe consultar_bd.py                      personas desaparecidas
    .venv\\Scripts\\python.exe consultar_bd.py --todas              todos los expedientes, incluidos los cerrados
    .venv\\Scripts\\python.exe consultar_bd.py --folio BUS-2026-0184 ficha y detecciones de una persona
    .venv\\Scripts\\python.exe consultar_bd.py --detecciones        últimas detecciones de todas las cámaras
    .venv\\Scripts\\python.exe consultar_bd.py --csv desaparecidos.csv  exporta la lista a Excel/CSV
"""
import argparse
import csv
import sys

from services.db_bootstrap import initialize_database
from services.db_service import database_available, get_db_connection

MISSING = '''SELECT folio, nombre_completo, edad, sexo, fecha_desaparicion, lugar_desaparicion, zona, estado,
                    fotografias, detecciones, ultima_deteccion, ultima_camara
             FROM v_personas_desaparecidas'''
EVERYONE = '''SELECT folio, nombre_completo, edad, sexo, fecha_desaparicion, lugar_desaparicion, zona, estado,
                     (SELECT COUNT(*) FROM fotografias_persona f WHERE f.persona_id = p.id),
                     (SELECT COUNT(*) FROM detecciones d WHERE d.persona_id = p.id),
                     (SELECT MAX(fecha_hora) FROM detecciones d WHERE d.persona_id = p.id), NULL
              FROM personas p WHERE folio IS NOT NULL ORDER BY folio'''
HEADERS = ['Folio', 'Nombre', 'Edad', 'Sexo', 'Desaparición', 'Lugar', 'Zona', 'Estado', 'Fotos',
           'Detecciones', 'Última detección', 'Última cámara']


def show(headers, rows):
    rows = [['' if v is None else str(v) for v in row] for row in rows]
    widths = [min(max([len(h)] + [len(r[i]) for r in rows]), 32) for i, h in enumerate(headers)]
    line = lambda values: '  '.join(v[:w].ljust(w) for v, w in zip(values, widths))
    print(line(headers))
    print('  '.join('-' * w for w in widths))
    for row in rows:
        print(line(row))
    print(f'\n{len(rows)} registro(s)')


def main():
    parser = argparse.ArgumentParser(description='Consulta la base de datos de personas desaparecidas.')
    parser.add_argument('--todas', action='store_true', help='incluye expedientes localizados o cerrados')
    parser.add_argument('--folio', help='ficha completa de un expediente')
    parser.add_argument('--detecciones', action='store_true', help='últimas 30 detecciones')
    parser.add_argument('--csv', metavar='ARCHIVO', help='exporta la lista a un archivo CSV')
    args = parser.parse_args()

    if not database_available():
        sys.exit('PostgreSQL no responde en localhost:5432. Enciende Docker Desktop y ejecuta: docker compose up -d')
    initialize_database()

    with get_db_connection() as conn, conn.cursor() as cur:
        if args.folio:
            cur.execute('''SELECT folio, nombre_completo, edad, sexo, estatura, complexion, tez, cabello, ojos,
                                  vestimenta, senas_particulares, descripcion_fisica, fecha_desaparicion,
                                  hora_desaparicion, lugar_desaparicion, zona, estado, responsable, fecha_reporte
                           FROM personas WHERE folio = %s''', (args.folio,))
            person = cur.fetchone()
            if not person:
                sys.exit(f'No existe el expediente {args.folio}.')
            labels = ['Folio', 'Nombre', 'Edad', 'Sexo', 'Estatura', 'Complexión', 'Tez', 'Cabello', 'Ojos',
                      'Vestimenta', 'Señas particulares', 'Descripción', 'Fecha de desaparición', 'Hora',
                      'Lugar', 'Zona', 'Estado', 'Responsable', 'Reportado']
            for label, value in zip(labels, person):
                print(f'{label + ":":24} {value if value is not None else "—"}')
            cur.execute('''SELECT codigo, fecha_hora, codigo_camara, similitud, calidad, estado
                           FROM detecciones WHERE folio = %s ORDER BY fecha_hora DESC''', (args.folio,))
            print('\nDetecciones:')
            show(['Código', 'Fecha y hora', 'Cámara', 'Similitud %', 'Calidad', 'Estado'], cur.fetchall())
            return
        if args.detecciones:
            cur.execute('''SELECT d.codigo, d.fecha_hora, d.codigo_camara, d.folio, p.nombre_completo, d.similitud,
                                  d.estado
                           FROM detecciones d LEFT JOIN personas p ON p.id = d.persona_id
                           ORDER BY d.fecha_hora DESC NULLS LAST LIMIT 30''')
            show(['Código', 'Fecha y hora', 'Cámara', 'Folio', 'Nombre', 'Similitud %', 'Estado'], cur.fetchall())
            return
        cur.execute(EVERYONE if args.todas else MISSING)
        rows = cur.fetchall()
    if args.csv:
        # utf-8-sig: Excel abre bien los acentos.
        with open(args.csv, 'w', newline='', encoding='utf-8-sig') as file:
            writer = csv.writer(file)
            writer.writerow(HEADERS)
            writer.writerows(rows)
        print(f'{len(rows)} registro(s) exportados a {args.csv}')
        return
    show(HEADERS, rows)


if __name__ == '__main__':
    main()
