# NEXO · Búsqueda y monitoreo

Frontend institucional de demostración para operadores y autoridades. Desarrollado en **Python y NiceGUI**, con páginas independientes, componentes reutilizables, revisión humana de coincidencias, seguimiento entre cámaras y simulación de solicitudes de auxilio por voz.

## Arranque rápido (Windows, sin Docker)

Doble clic en **`Iniciar NEXO.bat`**, en la carpeta del proyecto (si Windows dice «Windows
protegió su PC»: *Más información* → *Ejecutar de todas formas*). No cierres la ventana que se
abre mientras uses NEXO: cerrarla lo apaga. Es lo mismo que ejecutar en PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\iniciar.ps1
```

`iniciar.ps1` prepara el entorno y arranca NEXO en http://127.0.0.1:8080: repara un `.venv`
copiado de otra computadora (OneDrive, ZIP, USB), instala `requirements.txt` sólo si falta
algo, ejecuta el diagnóstico y levanta el servidor. **No necesita Docker**: los datos se
guardan solos en una base local SQLite (`data/nexo.db`). Para revisar el equipo sin arrancar:

```powershell
.\.venv\Scripts\python.exe -m services.diagnostico
```

El diagnóstico dice qué está listo y qué falta (paquetes, cámaras, micrófono, modelos facial y
de voz, token de Mapbox, base local y PostgreSQL), sin encender la cámara ni descargar nada.
El token público de Mapbox va en `.env` (ver `.env.example`); sin él, el mapa se dibuja con
MapLibre y teselas libres de CARTO.

## Recuperación del 24 de septiembre de 2026

Tres funciones se perdieron al fusionar ramas (en `dd01b0b` desapareció el arranque automático
del monitoreo continuo) o no se habían terminado. Quedaron recuperadas y completas:

| Función | Qué hace ahora | Dónde verlo |
| --- | --- | --- |
| Cámara siempre activa con evidencia | Cámaras y micrófono se encienden solos al iniciar NEXO, aunque falte el modelo facial. Al escuchar «ayuda» u otra frase de auxilio se conserva por sí solo un **clip de 5 s antes y 5 s después** de la frase: video MP4 con el audio sincronizado, el WAV original y fotos alrededor de la frase, todo con SHA-256 | `/alerts` (aviso en el encabezado de todas las páginas) |
| Última posición y trayecto en el mapa | Une en orden dónde se vio a la persona, dibuja el trayecto entre cámaras (por calles con token de Mapbox), marca la **última posición conocida**, dice si cada tramo es posible a pie, en vehículo o no, y sugiere dónde seguir buscando. También sigue a las personas vistas en un evento en las demás cámaras del equipo | `/tracking`, detalle del caso |
| Ficha de búsqueda contra la base | Una ficha registrada, una ficha nueva (OCR) o una fotografía autorizada se compara con todo lo que guardaron las cámaras. Cada resultado se muestra **lado a lado**: la ficha y la persona de la cámara, cuánto se parecen los rostros, sus características (edad, ropa) y el contexto de fecha y lugar. Las personas de un evento se comparan solas contra todas las fichas activas | `/search`, `/matches`, importación de fichas |
| Base de datos sin Docker | SQLite local (`data/nexo.db`) conserva casos, evidencia, candidatos, trayectos y bitácora entre reinicios. PostgreSQL sigue siendo opcional para compartir entre instancias | `python -m services.diagnostico` |

Ninguna de estas funciones identifica a nadie: todo resultado queda pendiente de revisión humana
(operador → supervisor), y los avisos y listas muestran niveles (ALTA, MEDIA, BAJA), no cifras.

El reconocimiento facial usa InsightFace (modelo `buffalo_l`) sobre las fotografías de fichas y casos y sobre la webcam del equipo en `/live`; la red CCTV, la reidentificación y el seguimiento entre cámaras siguen simulados. Las páginas consumen servicios de Python reemplazables. No hay frontend separado, Node.js ni pasos de compilación de JavaScript. NiceGUI administra sus propias dependencias web internas.

## Requisitos e instalación

- Python **3.11 o superior**; verificado con Python 3.12.13 y NiceGUI 3.17.1.
- Navegador moderno. Diseño principal de escritorio, con adaptación a tablet.
- Conexión a Internet para instalar dependencias. Los recursos de demostración son locales.

Desde la carpeta del proyecto:

```bash
python -m venv venv
```

Windows, PowerShell:

```powershell
venv\Scripts\Activate.ps1
```

Windows, CMD:

```bat
venv\Scripts\activate
```

macOS / Linux:

```bash
source venv/bin/activate
```
               
Instalar y ejecutar:

```bash
python -m pip install -r requirements.txt
python main.py
```

**Los modelos se descargan solos.** La primera vez que arranca, NEXO descarga en segundo plano
el modelo facial (unos 280 MB, en `~/.insightface`) y el de voz (unos 145 MB, en la caché de
Hugging Face). El encabezado muestra el avance («DESCARGANDO RECONOCIMIENTO FACIAL · 120 MB») y,
al terminar, el reconocimiento se activa sin reiniciar; mientras tanto la cámara ya graba. Sólo
esa vez se necesita internet: sin conexión, NEXO lo vuelve a intentar solo cada minuto. Para
descargarlo por adelantado y hacer una autoprueba sigue existiendo
`python -m services.face_engine`; ver [Reconocimiento facial](#reconocimiento-facial-insightface).

Se abre **http://127.0.0.1:8080** en el navegador, con redirección al centro de monitoreo. No requiere claves de API ni una base de datos. Si ya existe el entorno `.venv` preparado en este equipo, puede ejecutarse directamente con:

```powershell
.\.venv\Scripts\python.exe main.py
```

La app escucha únicamente en `127.0.0.1` de forma predeterminada. Variables opcionales: `NEXO_PORT` (8080), `NEXO_SHOW` (1; usar 0 para evitar abrir el navegador), `NEXO_HOST` y `NEXO_STORAGE_SECRET`. Para detener el servidor: `Ctrl+C` en su terminal.

## Vistas disponibles

| Ruta | Función |
| --- | --- |
| `/monitor` | Plano de cámaras, actividad, expedientes activos y vistas de interés |
| `/cases` | Tabla administrativa con búsqueda y filtros; alta de caso manual o desde alerta |
| `/cases/import-alert` | Importación de fichas de búsqueda (JPG, PNG, WebP o PDF): OCR, fotografía, coincidencias con fichas y con lo que guardaron las cámaras, y alta de caso |
| `/cases/{case_id}` | Referencias, información del reporte, detecciones, trayecto con última posición y línea temporal |
| `/search` | Búsqueda por ficha: una ficha o fotografía autorizada contra las capturas de las cámaras y las demás fichas, con comparación lado a lado |
| `/cameras` | CCTV 2 × 2, 3 × 3 y 4 × 4; filtros, grupos y panel por cámara |
| `/live` | Cámaras del equipo (laptop, USB y celular) en monitoreo continuo: reconocen a las personas en búsqueda, siguen a las personas de un evento y guardan los segundos alrededor de una frase de auxilio |
| `/matches` | Comparación lado a lado (ficha ↔ cámara), descarte, escalamiento y revisión |
| `/tracking` | Trayecto estimado de una ficha o de una persona de un evento, última posición conocida, tramos y dónde seguir buscando |
| `/alerts` | Evidencia de auxilio: clip de video con audio, fotos, WAV original, integridad, personas del evento, coincidencias con fichas, revisión y solicitudes de eliminación |
| `/voice` | Servicio de detección por micrófono, último análisis e historial reciente |
| `/history` | Bitácora filtrable con usuario, cámara, caso y resultado |
| `/users` | Usuarios y permisos por rol |
| `/settings` | Preferencias de referencia y puntos de integración |

Los parámetros `case_id`, `match_id`, `camera_id` y `alert_id` permiten enlaces directos desde otros módulos.

## Demostración de principio a fin

1. Abrir `/monitor` y seleccionar **Elena Robles (ficticia)**, folio `BUS-2026-0184`.
2. Consultar sus referencias y las detecciones: `CAM-004` a las 10:21:14, `CAM-007` a las 10:23:02 y `CAM-008` a las 10:25:41 (las tres cámaras del equipo, a pocos metros entre sí).
3. Abrir una detección en **Coincidencias**. Comparar lado a lado la ficha y la captura: parecido facial, edad, ropa, fecha y lugar. El operador descarta o solicita revisión; sólo un supervisor valida. Usuario, estado y hora quedan registrados en la bitácora.
4. Abrir **Mapa y seguimiento**. El mapa une las detecciones en orden, dibuja el trayecto estimado (por calles con token de Mapbox), marca la **última posición conocida** con un anillo y dice si cada tramo era posible a pie o en vehículo. Es una estimación: cada punto sigue pendiente de validación. Las detecciones descartadas salen del trayecto.
5. Ir a `/voice`: la detección ya está escuchando (arranca sola con NEXO). No se escribe ninguna frase: el sistema escucha el micrófono local.
6. Conversar con normalidad. Una narración pasada como `ayer necesité ayuda con una tarea` se clasifica NORMAL y no genera evidencia.
7. Decir una petición actual, por ejemplo `por favor déjame, me están siguiendo`. El sistema crea `EVENT-AAAAMMDD-NNNNN` y, sin que nadie lo pida, conserva 5 s antes y 5 s después de la frase: el clip de video con audio, el WAV original y fotos; calcula sus SHA-256 y lo envía a revisión. El encabezado de todas las páginas avisa del evento.
8. Abrir `/alerts` (o el aviso del encabezado), ver el clip, las fotos y las personas del evento, y elegir **CONFIRMAR PARA ATENCIÓN**, **MARCAR FALSO POSITIVO**, **ENVIAR A REVISIÓN** o **SOLICITAR ELIMINACIÓN**. No existe un botón de borrado: un supervisor distinto aprueba o rechaza la solicitud.
9. Probar **Nueva búsqueda**. Admite datos desconocidos y hasta cinco imágenes PNG, JPG o WebP de 5 MB cada una. Es obligatorio indicar un nombre o escribir «Persona desconocida». Las referencias se mantienen en memoria; su huella facial se calcula al comparar una ficha importada.
10. El menú de cuenta permite cambiar entre sesiones de prueba. El Operador puede gestionar búsquedas y revisiones; Supervisor también puede editar preferencias y frases; Administrador puede modificar permisos de otros usuarios. Las funciones de servicio comprueban el permiso antes de mutar datos.

## Arquitectura y trabajo por módulos

```text
main.py                  # arranque, archivos estáticos y registro de rutas
config.py                # configuración de ejecución
theme.py                 # tema común
pages/                   # una página NiceGUI por módulo
components/              # navegación, mapas, CCTV, tablas, perfiles y consolas
services/                # contratos que consume exclusivamente la interfaz
models/                  # dataclasses independientes de la interfaz
mocks/                   # semillas de datos ficticios
assets/css/              # estilos comunes y puntos de adaptación
assets/icons/            # identidad del sistema
assets/demo/             # plano, retratos, escenas y audio de prueba locales
assets/build_demo.py     # generador de recursos vectoriales y tono sintético
tests/                   # recorrido integral mediante simulador de NiceGUI
```

`services/store.py` concentra el repositorio temporal. Las páginas y componentes **no importan `mocks` ni el repositorio**. Los datos iniciales incluyen cuatro casos, dieciséis cámaras, diez detecciones, seis coincidencias y registros de historial. Voz y alertas comienzan vacías: sólo se llenan con audio real escuchado durante la sesión.

| Integración | Archivos principales |
| --- | --- |
| Gestión de reportes | `services/cases_service.py`, `models/person.py`, `models/search_case.py` |
| Importación de alertas | `services/alert_import_service.py`, `models/alert_import_record.py`, `components/alert_preview.py` |
| Reconocimiento facial | `services/face_engine.py`, `services/facial_service.py`, `models/detection.py`, `models/match.py` |
| Reconocimiento en vivo | `services/live_recognition_service.py`, `pages/live.py` |
| Cámaras | `services/cameras_service.py`, `models/camera.py`, `components/camera_feed.py` |
| Reidentificación / seguimiento | `services/tracking_service.py`, `components/map_view.py` |
| Voz e intenciones | `services/voice_service.py`, `models/voice_event.py` |
| Escucha continua | `services/monitoring_service.py`, `services/audio_buffer.py` |
| Asistente administrativo | `services/admin_voice_assistant_service.py`, `components/admin_voice_assistant.py`, `models/assistant_command.py` |
| Evidencia y eliminación | `services/evidence_service.py`, `models/evidence_event.py`, `models/deletion_request.py` |
| Alertas y seguimiento | `services/alerts_service.py`, `models/alert.py` |
| Usuarios, auditoría y backend | `services/users_service.py`, `services/history_service.py`, `services/store.py` |

Para conectar un módulo real, conserva las funciones públicas y los tipos de retorno del servicio correspondiente. Por ejemplo, reemplaza la consulta de `get_matches(case_id)` por el adaptador al módulo facial, y conserva `validate_match`, `reject_match` y `request_review` como decisiones explícitas del operador. `get_tracking_history` devuelve `TrackingEvent` ordenados cronológicamente. La voz debe entregar `VoiceEvent` al servicio de alertas; `create_voice_alert` es idempotente respecto al identificador del evento.

Las operaciones de cámara/IA que tarden deben implementarse como funciones asíncronas o tareas fuera del hilo de UI; los componentes `LoadingState`, `ErrorState` y `EmptyState` están disponibles. Para una geografía real, reemplaza el plano local dentro de `MapView` por el proveedor cartográfico elegido y amplía `Camera` con coordenadas geográficas. No interpretes los porcentajes `x`/`y` de este plano como latitud/longitud.

FastAPI está disponible a través de `nicegui.app` si después se necesitan endpoints internos. En esta versión no se agregan endpoints de integración ficticios ni conexiones externas innecesarias.

## Datos, sesiones y límites de esta versión

- Todos los nombres son ficticios. Los retratos y capturas son **ilustraciones vectoriales sintéticas**, no fotografías de personas reales. El módulo de voz trabaja exclusivamente con audio real del micrófono: no existen campos para escribir frases de prueba.
- El módulo de voz permite micrófono local y transcripción con faster-whisper. El reconocimiento facial es real sobre fotografías de fichas y casos y sobre las cámaras del equipo (`/live`: laptop, USB y celular); las demás cámaras de la red siguen simuladas. Los estados y similitudes son ejemplos para revisión humana. Confirmar un evento no confirma un delito.
- Lo registrado se guarda en la base local SQLite `data/nexo.db` (excluida de Git) y **sobrevive a un reinicio** sin Docker ni instalaciones. Sin compartir una base, cada instancia sólo ve lo suyo. El almacenamiento de sesión de NiceGUI está en `.nicegui/`, excluido de Git.
- Con PostgreSQL disponible (ver «Base de datos compartida del equipo» abajo), NEXO además sincroniza casos, cámaras, detecciones y la bitácora cada `DB_SYNC_SECONDS`, así que las cuatro personas del equipo ven el mismo historial sin importar desde qué instancia se generó.
- El selector de cuenta sirve para demostrar roles; **no es autenticación de producción**. La app no incluye SSO, gestión de credenciales, retención de evidencias ni auditoría inmutable. Estos puntos deben implementarse en los adaptadores de seguridad/backend antes de usar datos reales.
- Las preferencias de configuración se guardan como valores de referencia; no activan servicios ni políticas reales.
- Las escenas CCTV son estáticas. La actualización del monitor consulta los servicios simulados cada 15 segundos y la tabla de alertas cada 10 segundos.
- Las fechas iniciales de la demo son del 23 de septiembre de 2026. Las acciones del operador registran la hora local del equipo. El seguimiento muestra tiempo entre detecciones, sin sugerir que una captura de prueba sea una ubicación en vivo.

## Verificación

```bash
python -m unittest discover -s tests -v
```

Las pruebas usan el simulador de usuarios de NiceGUI y `unittest`, sin dependencias de desarrollo adicionales. Recorren las once vistas, filtran casos, registran uno nuevo, cambian revisiones, prueban la cámara desconectada, ejecutan el flujo de voz completo (buffer, transcripción, contexto, evidencia, integridad, revisión y eliminación autorizada) y verifican restricciones de permisos y entradas inválidas. Los datos y la carpeta de evidencia del test están aislados del servidor en ejecución.

`tests/test_event_evidence.py` recorre la evidencia automática con cuadros y audio sintéticos (clip de 10 s centrado en la frase, audio AAC dentro del MP4, SHA-256 de audio y video, cámara de respaldo, otros ángulos, fotos antes y después de la frase); `tests/test_route_and_fichas.py`, el trayecto (orden, paradas, tramos imposibles, seguimiento de las personas de un evento) y el cotejo con fichas (comparación automática, distancia y tiempo desde la desaparición, rasgos visibles, búsqueda sin crear candidatos); `tests/test_local_db.py`, la base local (ida y vuelta completa simulando un reinicio). Ninguna necesita cámara, micrófono ni modelos.

El arranque y las rutas también se comprobaron en un navegador real: reproducción del clip con audio en `/alerts`, comparación lado a lado, trayecto por calles con Mapbox y en línea recta con MapLibre (sin token), y búsqueda por ficha.

Referencia del framework: [documentación oficial de NiceGUI](https://nicegui.io/documentation).

## Base de datos compartida del equipo

`docker-compose.yml` levanta PostgreSQL con pgvector y, en el puerto `8082`, Adminer
para revisar las tablas desde el navegador. Es **opcional**: sin ella, NEXO funciona
igual, con su base local SQLite (`data/nexo.db`, ver «Base de datos local» más abajo).

```bash
docker compose up -d postgres_db
```

Al arrancar, cada instancia se conecta sola (`services/db_sync.py`, revisado cada
`DB_SYNC_SECONDS`, 5 s por defecto) y `services/db_bootstrap.py` crea o actualiza el
esquema (`personas`, `camaras`, `detecciones`, `historial_operaciones`, etc.) sin
borrar nada existente. Si el equipo son varias personas con instancias separadas, las
cuatro deben apuntar a la **misma** base para compartir información: en las que no son
el anfitrión, define `DATABASE_URL` con la IP de esa máquina antes de `python main.py`
(`docker-compose.yml` ya expone `5432` a la red, no sólo a `localhost`):

```bash
export DATABASE_URL="dbname=db_desaparecidos user=admin password=mi_password_seguro host=<IP_DEL_ANFITRION> port=5432"
python main.py
```

Se sincronizan casos, fotografías, cámaras y detecciones (última versión manda), y la
**bitácora** (`/history`) de forma distinta porque es un registro histórico, no un
estado que se sobrescribe: cada acción se guarda una sola vez (tabla
`historial_operaciones`, con la columna «Dispositivo» que identifica de qué equipo
vino, `NEXO_DEVICE_ID` o el nombre de host por defecto) y cada instancia trae también
las que registraron las demás, así que las cuatro personas terminan viendo el mismo
historial sin importar quién cerró su sesión. Desactívalo con `NEXO_DB_SYNC=0` si por
algún motivo no quieres que una instancia sincronice.

Sin conexión (contenedor apagado, sin red, credenciales incorrectas, o sin los paquetes
`psycopg`/`pgvector`) la aplicación **no se cae**: sigue funcionando con su base local,
reintentando solo cada `DB_SYNC_SECONDS` y avisando en la consola del servidor
(`services/db_sync.py:database.status` queda en `DESCONECTADA` o `ERROR`). Con la base
compartida conectada, los rostros de cada evento de auxilio también se suben
(`capturas_alerta`) para que la búsqueda por ficha de las demás instancias los encuentre.

## Base de datos local (sin Docker)

`services/local_db.py` guarda en `data/nexo.db` (SQLite, incluido en Python) los
expedientes, detecciones, coincidencias, evidencias, fotos de eventos, personas vistas en
eventos, perfiles de búsqueda, candidatos, reapariciones, solicitudes de eliminación,
alertas, importaciones, usuarios, preferencias y la bitácora completa. Al arrancar carga lo
guardado sobre los datos de demostración (la base manda) y después guarda cada
`NEXO_LOCAL_DB_SAVE_SECONDS` (3 s) sólo lo que cambió, y una última vez al cerrar. La
conversación ordinaria nunca se guarda: sólo los eventos de voz que sostienen una alerta.
Los archivos de evidencia (WAV, MP4, JPG) siguen en `evidence/`.

- Empezar de cero: detén NEXO y borra `data/nexo.db` (y `evidence/` si también quieres
  descartar la evidencia de prueba).
- Desactivarla: `NEXO_LOCAL_DB=0`. Otra ubicación: `NEXO_LOCAL_DB_PATH`.
- Si la carpeta del proyecto se sincroniza con OneDrive y la abren varias computadoras a la
  vez, guarda la base fuera de la carpeta sincronizada (un archivo SQLite abierto en dos
  equipos puede dañarse), por ejemplo en `.env`:
  `NEXO_LOCAL_DB_PATH=C:\Users\<usuario>\AppData\Local\NEXO\nexo.db`. Para compartir datos
  entre equipos usa PostgreSQL.

## Monitoreo continuo y evidencia de video

Las cámaras del equipo (laptop `CAM-008`, webcam USB `CAM-007` y celular enlazado `CAM-004`)
y el micrófono se incorporan solos al iniciar NEXO (`services/camera_monitor_service.py`) y
se reintentan cada 20 s si están ocupados o desconectados. La cámara transmite aunque el
modelo facial no esté descargado: el reconocimiento es una capa aparte que se carga en
segundo plano. `/live` permite **pausar** una cámara (queda libre y el monitoreo no la reabre
sola) y reanudarla.

Cada cámara guarda en memoria sus últimos ~40 s de video (hasta 12 cuadros por segundo, sin
espejo). Cuando la voz detecta una posible solicitud de auxilio:

1. Se ubica el **instante exacto de la frase** con los segmentos de Whisper, no el borde de la
   ventana analizada, y se alinea con el reloj de las cámaras.
2. Se conserva el audio de `EVIDENCE_PRE_SECONDS` antes a `EVIDENCE_POST_SECONDS` después
   (5 s y 5 s) como WAV original con su SHA-256.
3. Se escribe el **clip MP4 (H.264 + AAC)** de esos mismos 10 s con el audio sincronizado, con
   la marca de tiempo real de cada cuadro, y su SHA-256. Si la cámara del micrófono no
   transmite, se usa otra cámara del equipo en vivo; las demás cámaras en vivo guardan su
   ángulo del mismo instante.
4. Se guardan **fotos** a -2, 0, +1, +2 y +4 s de la frase; con el modelo facial, cada persona
   que aparece queda como persona del evento (recorte, edad aparente, color de la ropa).
5. Esas personas se comparan solas con todas las fichas activas y se buscan durante
   `NEXO_EVENT_TRACKING_MINUTES` (60) en las demás cámaras del equipo (seguimiento
   provisional). «Iniciar seguimiento» en `/alerts` lo confirma por 12 h; un falso positivo lo
   detiene.

Todo lo anterior comparte el mismo `event_id` y aparece en `/alerts?event_id=…`; el
encabezado de todas las páginas avisa de los eventos sin revisar. Variables:
`NEXO_EVIDENCE_PRE_SECONDS`, `NEXO_EVIDENCE_POST_SECONDS`, `NEXO_CAMERA_AUTOSTART`.

## Mapa: trayecto y última posición

`/tracking` (y el detalle de cada caso) une en orden cronológico dónde se vio a la persona
(`services/route_service.py`): las detecciones de una ficha (sin las descartadas) y sus
candidatos vigentes, o, para una persona vista en un evento, el evento y sus reapariciones en
otras cámaras. Para cada tramo calcula la distancia real, el tiempo y la velocidad implícita,
y dice si era **posible a pie**, **en vehículo** o **no es posible en ese tiempo** (en cuyo
caso una de las dos observaciones probablemente es un falso positivo). El mapa dibuja paradas
numeradas, flechas de dirección y un anillo en la **última posición conocida**, y sugiere las
cámaras contiguas donde seguir buscando. Se actualiza cada 5 s: si alguien camina de la cámara
A a la B, el trayecto crece mientras se mira.

Con token de Mapbox cada tramo se traza **por calles** (Mapbox Directions, a pie o en
vehículo); sin token, en línea recta sobre MapLibre. Es un trayecto estimado: el camino exacto
entre dos cámaras no se observa. La posición real de las cámaras del equipo se configura en
`.env`: `NEXO_CAMERA_LATLNG`, `NEXO_CAMERA_2_LATLNG`, `NEXO_CAMERA_3_LATLNG` (por defecto,
tres puntos a pocos metros dentro del Tec de Nuevo León).

## Búsqueda por ficha

`/search` responde «¿esta persona ya aparece en lo que registraron las cámaras?». La
referencia puede ser una ficha registrada, una ficha nueva (imagen o PDF, se lee con OCR y se
recorta la foto) o una **fotografía autorizada** (hay que confirmarlo). Se compara contra las
personas vistas en eventos de auxilio, las detecciones con huella facial, la base compartida
si está conectada, y las demás fichas (posibles duplicados). Consultar no crea candidatos: el
operador envía a revisión lo que corresponda.

Cada resultado se muestra **lado a lado** (`components/face_comparison.py`): la ficha y la
persona de la cámara, el **parecido facial** (cuánto se parecen los dos rostros según el
modelo; no es la probabilidad de identidad), y una tabla ficha-frente-a-cámara con edad
(declarada vs. aparente), vestimenta (declarada vs. color de la ropa superior), fecha
(desaparición vs. captura) y lugar (último lugar conocido vs. cámara, con distancia real y si
era alcanzable en el tiempo transcurrido). La misma comparación aparece en `/matches`,
supervisión, la evidencia de un evento y la importación de fichas. Nada de eso descarta a
nadie ni confirma una identidad.

Además, sin que nadie lo pida: las personas de un evento se comparan con todas las fichas
activas, y una ficha nueva se compara con lo que las cámaras ya guardaron (si el modelo facial
está cargado). Requiere el modelo facial, que NEXO descarga solo la primera vez que arranca
(la página se habilita sola al terminar).

## Importar alertas de búsqueda (OCR)

Permite partir de una ficha real de persona desaparecida en lugar de capturar todo
a mano. Es un **apoyo a la decisión**: ni identifica personas ni confirma
localizaciones.

### Flujo

```text
/cases → Crear caso desde alerta → /cases/import-alert

1 Subir ficha (JPG, PNG, WebP o PDF, hasta 10 MB)
2 Extracción automática: OCR + recorte de la fotografía
3 Revisión y corrección de los campos por el operador
4 Coincidencias: textual, facial (preparada) y contextual
5 Crear caso nuevo · Vincular con caso existente · Enviar a revisión · Cancelar
```

### Qué se extrae

Nombre completo, folio de la alerta, edad, sexo reportado, nacionalidad, fecha de
desaparición, fecha del reporte, lugar de los hechos, descripción física, señas
particulares, vestimenta, autoridad emisora y carpeta de investigación. Lo que no
pueda leerse se queda vacío: **nunca se inventa un dato**. El estado de extracción
se muestra como `EXTRACCION_COMPLETA`, `EXTRACCION_PARCIAL`, `SIN_TEXTO_RECONOCIDO`
o `REVISADA_POR_OPERADOR`, y todos los campos son editables antes de continuar.

### Motores de lectura

| Etapa | Herramienta | Nota |
|---|---|---|
| PDF con capa de texto | PyMuPDF | No necesita OCR |
| PDF escaneado / imagen | Tesseract si está instalado, si no **RapidOCR** | RapidOCR es autónomo: no requiere binarios externos |
| Fotografía | OpenCV: rostro (Haar) → región fotográfica → imagen incrustada del PDF | Recorte orientativo, revisable |

El OCR pega palabras en los títulos en negritas («NOMBRECOMPLETO:»), así que el
lector compara las etiquetas sin espacios ni acentos y admite la fecha en formatos
`22 de septiembre de 2026`, `23/09/2026` o `2026-09-22`. Si ningún motor está
disponible, el módulo lo dice y el operador captura los datos a mano.

### Las tres comparaciones

1. **Textual** — compara con los casos existentes por nombre, sexo, rango de edad,
   lugar, fecha, señas y vestimenta. Devuelve un puntaje de similitud y un nivel
   `ALTA`, `MEDIA` o `BAJA`, siempre redactado como «coincidencia textual», nunca
   como identidad.
2. **Facial** — `prepare_face_reference(photo_path)` detecta el rostro de la
   fotografía recortada y calcula su huella de 512 números con InsightFace;
   `match_face_reference(face_reference)` la compara con las fotografías de los
   casos registrados y devuelve `COINCIDENCIAS_FACIALES` con nivel y porcentaje de
   similitud, o `SIN_COINCIDENCIAS_FACIALES`. `compare_with_face_database(reference_photo)`
   hace ambos pasos. Si la foto no tiene un rostro detectable el estado es
   `SIN_ROSTRO_DETECTADO`, y si el modelo no puede cargarse, `ERROR_MODULO_FACIAL`
   con el motivo. Sin InsightFace instalado el estado sigue siendo
   `PENDIENTE_MODULO_FACIAL` y **no se asigna ningún nivel**: inventarlo sería
   fabricar una coincidencia que nadie calculó. Con la huella lista, la ficha también
   se busca en lo que guardaron las cámaras (**Apariciones en cámaras**: personas de
   eventos, detecciones y base compartida), con la comparación lado a lado.
3. **Contextual** — cruza el lugar reportado con las cámaras de la zona, la fecha
   con las detecciones dentro de ±15 días (`IMPORT_DATE_WINDOW_DAYS`) y resume las
   cámaras relacionadas.

### Acciones finales y retención

Crear caso usa el servicio existente `create_case`, con la fotografía recortada
como referencia y los datos de la alerta en la descripción; vincular asocia la
alerta a un caso ya registrado. Ambas dejan el expediente pendiente de validación.
Cancelar **elimina los archivos temporales**. Las fichas viven en `imports/`
(`documents/` y `photos/`), carpeta excluida de Git y separada de `evidence/`: una
ficha importada no es evidencia de auxilio. Cada paso —análisis, corrección de
campos, comparación, alta, vínculo, revisión y cancelación— queda en la bitácora.

## Reconocimiento facial (InsightFace)

Convierte cada rostro en una huella de 512 números con el modelo preentrenado
`buffalo_l` de [InsightFace](https://github.com/deepinsight/insightface/tree/master/python-package).
No hay que entrenar nada: registrar a una persona es calcular la huella de su
fotografía, y dos fotografías de la misma persona dan huellas parecidas.

### Instalación y autoprueba

`requirements.txt` ya incluye `insightface` y `onnxruntime`. No hace falta ejecutar nada más:
NEXO descarga el modelo solo la primera vez que arranca (`services/model_setup.py`), en
`~/.insightface/models/buffalo_l`, fuera del proyecto para que no viaje en el repositorio ni en
los ZIP. Para descargarlo por adelantado y comprobar la instalación:

```bash
python -m services.face_engine
```

Descarga el modelo si falta y ejecuta una autoprueba con la foto de ejemplo de la librería:

```text
Motor: InsightFace buffalo_l
InsightFace instalado: sí
Modelo: C:\Users\...\.insightface\models\buffalo_l (descargado)
Modelo cargado en 1.4 s
Autoprueba: OK · 6 rostros · misma persona 0.97 · personas distintas máx. 0.21 (umbral 0.45)
```

Para revisar una foto concreta: `python -m services.face_engine --imagen ruta/foto.jpg`.
Funciona en CPU; una laptop normal basta (alrededor de medio segundo por imagen).

Prueba en vivo con la webcam: `python -m services.face_engine --camara` abre una ventana
que enmarca cada rostro. **R** registra el rostro más visible como referencia y desde ese
momento cada rostro muestra su similitud y nivel (verde ALTA, amarillo MEDIA, naranja
BAJA, gris sin coincidencia); **Q** o **Esc** salen. Con `--referencia foto.jpg` compara
contra una fotografía, y `--camara 1` usa una segunda cámara. Los cuadros sólo se
analizan en memoria: no se guarda nada. Si la ventana indica «Imagen negra», la cámara
funciona pero no recibe luz: destapa el lente o ilumina la escena.

`requirements.txt` usa `opencv-python` y ya no `opencv-python-headless`: RapidOCR e
InsightFace dependen de la primera, y tener ambas instaladas deja dos copias de `cv2`
que se pisan entre sí.

### Uso desde otros módulos

```python
from services import face_engine

rostros = face_engine.analyze(imagen)   # ruta, bytes, data URL o cuadro BGR de OpenCV
rostro = face_engine.best_face(imagen)  # el rostro más visible, o None
rostro.embedding                        # 512 float32 normalizados: columna vector(512) de pgvector
face_engine.similarity(a, b)            # similitud coseno
face_engine.level_of(0.63)              # 'ALTA', 'MEDIA', 'BAJA' o None
```

`facial_service.compare_with_cases(embedding)` compara una huella con las fotografías
de los casos registrados, y `get_matches(vector_busqueda=...)` busca en PostgreSQL con
el mismo umbral. El modelo se carga una sola vez, en el primer uso (unos segundos), y
admite llamadas desde varios hilos; la interfaz lo invoca con `run.io_bound` para no
congelarse.

### En vivo desde la web (`/live`)

Todo el flujo se hace desde el navegador, con las cámaras del equipo donde corre NEXO:

1. **Reconocimiento en vivo**: las cámaras ya están transmitiendo (arrancan solas con NEXO).
   Cada una se asocia a una cámara de la red (la de la laptop a `CAM-008 — Pasillo B`, la
   misma del micrófono). **PAUSAR** libera una cámara y **REANUDAR** la vuelve a encender.
2. **Registrar persona con esta cámara** toma la foto del rostro más visible y abre el
   formulario del caso con esa foto; también se puede registrar con una fotografía
   subida, o importando una ficha en `/cases/import-alert`.
3. Cada rostro aparece enmarcado con el folio, el nombre y la similitud de su caso más
   parecido, o «Sin coincidencia» en gris. Los casos nuevos se comparan a los pocos
   segundos, sin reiniciar.
4. Una coincidencia crea una **detección** y una **coincidencia pendiente de validación**
   con el recorte del rostro: aparece en `/matches`, en el detalle y el mapa del caso, en
   `/tracking`, en el monitor y en los eventos de la cámara, y queda en la bitácora. Se
   crea una por caso y cámara cada 30 s (`LIVE_DETECTION_COOLDOWN_SECONDS`); dentro de
   esa ventana se conserva la mejor captura.
5. Mientras una cámara está encendida, la cabecera de todas las páginas muestra
   «CÁMARA EN VIVO».

Si la voz detecta una posible solicitud de auxilio, el evento guarda el clip de 5 s antes y
5 s después con su audio, las fotos y los rostros que estaban en cuadro (se ven en
`/alerts`); ver «Monitoreo continuo y evidencia de video». Fuera de un evento, los cuadros
sólo existen en un anillo en memoria que se sobrescribe; se conserva únicamente el recorte
del rostro de cada posible coincidencia. `NEXO_CAMERA_INDEX` elige otra webcam.

### Umbrales y configuración

| Similitud | Nivel |
|---|---|
| 0.60 o más | ALTA |
| 0.50 o más | MEDIA |
| 0.45 o más | BAJA |
| menos de 0.45 | No se propone |

Son orientativos para `buffalo_l`: en la imagen de ejemplo la misma persona da 0.97 y
personas distintas no pasan de 0.21. Con fotos de cámara la similitud baja, así que
conviene ajustarlos probando con fotos del equipo. Ningún nivel confirma una
identidad: todo queda pendiente de validación humana.

Variables en `config.py`: `FACE_MATCH_THRESHOLD`, `FACE_LEVEL_MEDIUM`,
`FACE_LEVEL_HIGH`, `FACE_MIN_DET_SCORE` (0.5), `FACE_MODEL` (`buffalo_l`),
`FACE_MODEL_ROOT` (`~/.insightface`) y `FACE_AUTO_DOWNLOAD` (`true`: si falta el
modelo se descarga solo; con `false` se muestra el comando para descargarlo). En `.env`,
`NEXO_MODELS_AUTOPREPARE=false` evita que los modelos se preparen al arrancar (entonces se
cargan en el primer uso).

### Licencia y privacidad

- El código de InsightFace es MIT, pero **los modelos preentrenados son sólo para uso
  no comercial o de investigación**. Para el hackatón no hay problema; para un uso
  real con autoridades o comercial hay que obtener licencia de InsightFace o cambiar
  de modelo.
- Las huellas se calculan en el equipo: ninguna fotografía se envía a servicios
  externos. Las de los casos viven en memoria, en caché por fotografía, y se pierden
  al reiniciar.
- La edad que estima el modelo (`rostro.age`) es aproximada: sirve para ordenar,
  nunca para descartar.

### Verificación

`tests/test_face_engine.py` cubre la lectura de imágenes (incluidas rutas con acentos
y data URL), el orden por prominencia, los umbrales, el error claro cuando falta el
modelo y la comparación con casos. Si el modelo está descargado, también ejecuta
inferencia real: los seis rostros de la imagen de ejemplo, huellas de 512 números
normalizadas, misma persona sí y personas distintas no, y el recorrido completo
fotografía de ficha → caso registrado con nivel ALTA. Sin el modelo, esas pruebas se
omiten con el aviso de cómo descargarlo.

## Detección de auxilio por voz (audio real)

Instala las dependencias y arranca desde el directorio del proyecto:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

Si este entorno no tiene pip, usa el instalador local existente:

```powershell
.\.tools\uv.exe pip install --python .venv/Scripts/python.exe --cache-dir .tools/cache -r requirements.txt
.\.venv\Scripts\python.exe main.py
```

El módulo funciona **únicamente con audio capturado del micrófono**. La interfaz
no ofrece ningún campo para escribir frases ni simular eventos.

La escucha no es una pantalla aparte: pertenece a la cámara. Sobre la imagen de cada
cámara del equipo se lee su estado de escucha, y cuando oye una posible solicitud de
auxilio la propia cámara anuncia que conservó ese instante. Al abrir la cámara en
*Red de cámaras* aparecen su escucha, el último análisis y los eventos conservados
—imagen, audio y video del mismo `event_id`— con el enlace para que una autoridad los
revise y con la última ubicación registrada para continuar el seguimiento en el mapa.

```text
Micrófono
  ↓ captura continua en un buffer circular en memoria
Ventanas de 6 s (solapamiento de 2 s)
  ↓ faster-whisper (español)
Transcripción
  ↓ contexto de los últimos 20 s de conversación
IA contextual (significado e intención) + análisis acústico
  ↓ fusión
NORMAL · AMBIGUO · POSIBLE_AUXILIO · ALTA_PRIORIDAD
  ↓ sólo si corresponde
EvidenceEvent + audio original + SHA-256
  ↓
/alerts → revisión humana
```

### Cómo probar el flujo completo

1. Abre `/voice`. La parte superior muestra el estado del servicio, si hay
   micrófono disponible y la cámara asociada (`CAM-008 — Pasillo B`).
2. La detección ya está escuchando: arranca sola con NEXO (si Windows pregunta, permite el
   acceso al micrófono). El indicador de nivel confirma que entra audio. **PAUSAR
   DETECCIÓN** libera el micrófono y **REANUDAR DETECCIÓN** lo vuelve a abrir.
3. Conversen dos o tres personas con normalidad. Cada ventana analizada muestra
   transcripción, análisis, señales y resultado; nada se guarda en disco.

| Lo que se dice | Resultado esperado | Evidencia |
|---|---|---|
| «ayer comí tacos y se me atoró uno, ocupé ayuda» | NORMAL | No |
| «oye, no me sigas» tras conversación ordinaria | AMBIGUO o POSIBLE_AUXILIO | Según el análisis |
| «por favor déjame, necesito ayuda» | POSIBLE_AUXILIO | Sí |
| «suéltame, ayuda» con cambio acústico | ALTA_PRIORIDAD | Sí |

4. Cuando se crea un evento, la consola indica `EVENT-AAAAMMDD-NNNNN`, que el
   audio y el video quedaron protegidos y que está pendiente de revisión. El encabezado
   de todas las páginas lo avisa.
5. Abre `/alerts`, pulsa **Revisar** (o el aviso del encabezado) y reproduce el clip: 5 s
   antes y 5 s después de la frase, con su audio. El panel muestra las fotos, el WAV
   original, la verificación de integridad de ambos, las personas del evento, sus
   coincidencias con fichas, la transcripción y el análisis. Si ninguna cámara transmitía,
   el video queda **Pendiente de integración** y el audio sí se conserva.
6. Prueba **MARCAR FALSO POSITIVO**: cambia la clasificación de revisión y el
   audio permanece.
7. Prueba **SOLICITAR ELIMINACIÓN** con un motivo. El evento pasa a
   `DELETION_REQUESTED` y aparece «Solicitud enviada para autorización».
8. Cambia de cuenta a **Supervisor01** desde el menú de sesión y vuelve a
   `/alerts`. En **Solicitudes de eliminación** puedes **APROBAR** o **RECHAZAR**.
   Quien solicita no puede autorizar su propia solicitud.
9. Consulta `/history`: creación del evento, reproducción, revisión, solicitud y
   resolución quedan registradas.

### Evidencia, integridad y video

Cuando la clasificación es POSIBLE_AUXILIO o ALTA_PRIORIDAD se crea un
`EvidenceEvent` con su audio, su clip de video y sus fotos:

```text
evidence/
├── audio/EVENT-20260923-00001.wav            audio original (5 s antes y 5 s después)
├── video/EVENT-20260923-00001.mp4            clip H.264 + AAC de la cámara del evento
├── video/EVENT-20260923-00001-CAM-007.mp4    otro ángulo del mismo instante (si lo hay)
└── frames/EVENT-20260923-00001-F01.jpg …     fotos a -2, 0, +1, +2 y +4 s de la frase
```

- El fragmento abarca `EVIDENCE_PRE_SECONDS` (5) antes y `EVIDENCE_POST_SECONDS` (5)
  después del instante en que se dijo la frase, localizado con los segmentos de Whisper.
- El identificador es único por día y **nunca se sobrescribe un archivo**: si el
  nombre existe, se rechaza la escritura.
- Al guardarlo se calcula un **SHA-256** que se conserva en el evento. `/alerts`
  vuelve a calcularlo al abrir el detalle y muestra
  «✓ Archivo original verificado» sólo si coincide.
- El original es inmutable: la interfaz no edita, recorta ni reemplaza audio. Una
  versión procesada debe crearse como copia derivada, conservando el original.
- El clip se asocia con `attach_video_evidence(...)` de `services/evidence_service.py`
  (`video_file`, `video_start_timestamp`, `video_end_timestamp`, `video_status = "ATTACHED"`,
  `video_has_audio`, `video_camera_id` y `video_integrity_hash`); audio, video y fotos
  comparten el mismo `event_id`. `/alerts` verifica también el SHA-256 del video y ofrece
  descargar el MP4 original. Sin imagen de ninguna cámara, `video_status` queda en
  `PENDING_INTEGRATION`.

### Roles y control de eliminación

| Rol | Puede |
|---|---|
| Operador | Escuchar evidencia, revisar transcripción y análisis, confirmar para atención, marcar falso positivo, enviar a revisión y **solicitar** eliminación |
| Supervisor | Lo anterior, más **aprobar o rechazar** solicitudes de eliminación |
| Administrador | Lo anterior, más gestión de usuarios y consulta de auditoría completa |

Ningún rol puede borrar evidencia desde la interfaz: el botón de borrado no
existe. Los estados de revisión son `PENDIENTE_REVISION`, `EN_REVISION`,
`CONFIRMADO_PARA_ATENCION`, `FALSO_POSITIVO`, `DELETION_REQUESTED`,
`DELETION_APPROVED` y `DELETION_REJECTED`. Para el prototipo, una aprobación
registra `DELETION_APPROVED` y **no elimina el archivo físico**, de modo que una
demostración no pueda destruir evidencia por accidente. Toda solicitud guarda
quién la pidió, quién la resolvió, fecha, motivo, hash y evento; la bitácora de
esa operación permanece aunque más adelante se aplique una política de borrado.

### Privacidad: qué se conserva y qué no

- Las conversaciones ordinarias **sólo existen en memoria**. El audio vive en un
  buffer circular de unos 40 segundos que se sobrescribe continuamente y se borra
  al detener el monitoreo o al cerrar la página.
- El contexto conversacional conserva como máximo 8 segmentos de los últimos 20
  segundos; los segmentos antiguos se descartan si no pertenecen a un evento.
- **Sólo se escribe audio en disco cuando existe un posible evento de auxilio.**
  Los eventos NORMAL no generan archivo y su transcripción caduca automáticamente.
- La bitácora conserva identificadores, clasificaciones y acciones, no las
  conversaciones normales.
- La carpeta `evidence/` está excluida de Git: las grabaciones nunca se versionan.

### Micrófono y modelo

Configuración en `config.py`: `VOICE_MODEL` (`tiny`, `base` o `small`),
`VOICE_LANGUAGE='es'`, `AUDIO_SAMPLE_RATE=16000`, `AUDIO_WINDOW_SECONDS=6`,
`AUDIO_OVERLAP_SECONDS=2`, `EVIDENCE_PRE_SECONDS=5`, `EVIDENCE_POST_SECONDS=5`,
`AUDIO_RING_SECONDS` y `DEFAULT_CAMERA_ID`.

Whisper usa CPU/int8 y carga el modelo en la primera transcripción; puede
necesitar Internet para descargarlo. Se captura el dispositivo predeterminado del
equipo donde corre Python, no el micrófono de un navegador remoto. Sólo una
escucha puede usar el micrófono a la vez. No se fabrican porcentajes de
confianza: `confidence=None`; los metadatos reales de Whisper se conservan en el
evento y en `transcript_segments`.

El análisis acústico mide energía RMS, su variación y la relación frente a la
mediana reciente. `ACOUSTIC_CHANGE_RATIO=2.0` es un umbral experimental. Un
cambio acústico **no** crea alertas con semántica NORMAL o AMBIGUO, y una
petición actual dicha en voz baja sí puede crearlas: la decisión depende del
lenguaje y su contexto. No se infieren emociones; la interfaz sólo informa
«Cambio acústico significativo» o «Variación acústica moderada».

### Integración y autorización

`services/monitoring_service.py` orquesta captura, ventanas, transcripción,
contexto, fusión y evidencia. `services/voice_service.py` conserva transcripción
y clasificación, y `process_text` sigue siendo la entrada compartida.
`services/voice_integrations.py` ofrece `request_person_detection`,
`start_tracking_from_alert` y `execute_authority_command`; sus resultados
incluyen `mock=True`, salvo `request_person_detection`, que es real mientras el
reconocimiento en vivo (`/live`) usa esa cámara. La grabación del clip de video y el
seguimiento de las personas del evento entre las cámaras del equipo ya son reales
(`services/camera_monitor_service.py`, `services/tracking_service.py`); el seguimiento en
cámaras de la red simuladas sigue siendo un punto de integración.

El selector de usuario NO autentica: es una demostración de roles. Los permisos
(`review`, `deletion.request`, `deletion.approve`, `users`) se comprueban en los
servicios de Python, no en la interfaz.

Referencias de las APIs: [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
y [sounddevice](https://python-sounddevice.readthedocs.io/).

## Asistente de voz para administradores

Módulo **independiente** de la detección automática de auxilio: no comparte
buffer, contexto, evidencia ni almacenamiento. Es un atajo de navegación por voz.

### Cómo se usa

Con una sesión de rol **Administrador** aparece una bolita con micrófono fija en
la esquina inferior derecha de todas las páginas. Es push-to-talk con un solo
botón:

1. Toca la bolita → empieza a grabar, el botón se pone rojo con un pulso discreto
   y el panel muestra «● Escuchando…».
2. Toca **la misma bolita** → detiene la grabación y muestra «Procesando…».
3. faster-whisper transcribe (reutiliza el modelo ya cargado en memoria, no carga
   otro), la IA interpreta la intención y se ejecuta el comando.
4. El panel muestra lo que se dijo y el resultado; si corresponde, navega solo y
   deja una confirmación discreta en la página de destino.

Estados del botón: `IDLE` 🎙 · `LISTENING` ■ · `PROCESSING` … · `SUCCESS` ✓ ·
`ERROR` ! . Tras unos segundos vuelve solo a `IDLE`.

### Permisos

Sólo el rol **Administrador** tiene el permiso `assistant`. Para los demás roles
el botón no se dibuja **y además** `handle_command` vuelve a comprobar el rol en
el servidor, así que el comando no se ejecuta aunque alguien llame al servicio
directamente.

### Comandos que entiende

No hay que memorizar frases: el servicio interpreta lenguaje natural y varias
formas equivalentes producen la misma intención.

| Ejemplos hablados | Intención | Resultado |
|---|---|---|
| «búscame el folio 184», «abre el caso 184», «quiero ver el folio 184», «abre el caso BUS-2026-0184» | `OPEN_CASE` | Abre `/cases/BUS-2026-0184` |
| «busca a María López», «muéstrame el caso de María López» | `SEARCH_PERSON` | Abre el caso si hay una sola coincidencia |
| «muéstrame la última detección del folio 184», «¿dónde se detectó por última vez el caso 184?» | `SHOW_LAST_DETECTION` | Muestra cámara, ubicación y hora, y abre el seguimiento |
| «muéstrame las coincidencias del folio 184» | `SHOW_MATCHES` | Abre `/matches?case_id=…` |
| «muéstrame la cámara 8», «abre CAM-008», «abre la cámara ocho» | `OPEN_CAMERA` | Abre `/cameras?camera_id=CAM-008` |
| «muéstrame las alertas pendientes» | `SHOW_PENDING_ALERTS` | Abre `/alerts` filtrado por pendientes |
| «abre las alertas de hoy» | `SHOW_ALERTS` | Abre `/alerts` |
| «hola cómo estás», «pásame aquello de ayer» | `UNKNOWN_COMMAND` | «No entendí el comando. Intenta decirlo nuevamente.» y **no ejecuta nada** |

Si un nombre coincide con varias personas, el panel lista las opciones con su
folio y el administrador elige: el asistente nunca decide por él. Si falta el
dato necesario (folio, cámara o nombre) responde el problema en lugar de adivinar.

### Interpretación y fallback

`services/admin_voice_assistant_service.py` envía la transcripción al proveedor de
IA configurado (`AI_PROVIDER`, `AI_MODEL`, `AI_CONTEXT_URL`) pidiendo un JSON con
el esquema de `AssistantCommand`, validado con Pydantic. Si el proveedor no está
disponible, responde algo inválido o inventa una intención sin su dato obligatorio,
se usan reglas locales deterministas. Ambos caminos producen la misma estructura,
por ejemplo `{"intent": "OPEN_CASE", "folio": "184"}`.

### Límites de seguridad

El asistente sólo **busca, muestra, abre, consulta y navega**. No puede borrar
evidencia, aprobar eliminaciones, eliminar casos o usuarios, cambiar permisos ni
confirmar alertas por voz: esas intenciones no existen y cualquier otra se rechaza
en `execute`. Si en el futuro se agregan acciones sensibles deberán pedir
confirmación manual.

### Auditoría y audio

Cada comando ejecutado deja una entrada en la bitácora con usuario, fecha, frase
transcrita, intención y resultado; por ejemplo
`Admin01 · Comando de voz · "búscame el folio 184" → OPEN_CASE · SUCCESS`.
El audio del comando **no se guarda**: vive en memoria mientras se transcribe y se
descarta; nunca entra en `evidence/audio/`, que es exclusivo de la evidencia de
auxilio. Si el monitoreo de auxilio está escuchando, el micrófono está ocupado y
el asistente lo informa en lugar de competir por el dispositivo.

### IA contextual y fallback real

Configuración central en `config.py`:

```python
AI_CONTEXT_ENABLED = True
AI_PROVIDER = 'ollama'
AI_MODEL = 'qwen2.5:3b'
AI_CONTEXT_URL = 'http://127.0.0.1:11434'
AI_TIMEOUT_SECONDS = 15
CONTEXT_SECONDS = 20
CONTEXT_MAX_SEGMENTS = 8
AUDIO_WINDOW_SECONDS = 6
AUDIO_OVERLAP_SECONDS = 2
```

El adaptador Ollama usa `/api/chat`, esquema JSON y validación estricta con Pydantic.
La interfaz sólo conoce `analyze_conversation_context`. Para integrar otro proveedor,
agrega un adaptador al registro `PROVIDERS` que devuelva `SemanticAnalysis`.
El prompt trata las transcripciones como datos y pide explicaciones breves;
no solicita razonamiento interno ni conclusiones legales.

No se instala ni descarga automáticamente un LLM. En este entorno no se encontró
Ollama disponible: las pruebas de los diez escenarios verifican **Fallback local**.
El contrato de IA se probó con transporte simulado, no con inferencia real de un LLM.
Para usar IA local, instala [Ollama](https://ollama.com/download), descarga el modelo
con `ollama pull qwen2.5:3b` y deja su servidor local ejecutándose. Reinicia NEXO y
comprueba que la consola muestre **IA contextual**. La carga inicial puede superar
el timeout; precarga el modelo con `ollama run qwen2.5:3b` si fuera necesario.
El modelo es intercambiable mediante `AI_MODEL`; sus resultados deben validarse
con los mismos ejemplos antes de una presentación.

Si el servicio falla, no existe modelo, vence el timeout o el JSON es inválido,
se usa **Fallback local** con motivo visible. También puedes forzarlo usando
`AI_CONTEXT_ENABLED=False`. El fallback distingue indicadores de pasado, citas,
hipótesis, ayuda cotidiana y expresiones actuales, pero no comprende todos los
matices: ironía, citas mezcladas y negaciones complejas pueden fallar. Es un
prototipo para revisión humana, no un sistema validado de detección de emergencias.

Referencia del contrato: [salida estructurada de Ollama](https://docs.ollama.com/capabilities/structured-outputs).
Modelo configurable: [Qwen2.5 3B](https://ollama.com/library/qwen2.5:3b).

### Retención del prototipo

- El audio en vivo vive en un buffer circular en memoria. Sólo se escribe en
  disco el fragmento asociado a un posible evento de auxilio; el resto se
  sobrescribe y se descarta al detener el monitoreo o cerrar la página.
- El contexto conversacional guarda como máximo 8 segmentos de los últimos 20
  segundos y 2000 caracteres por segmento.
- Los eventos NORMAL se muestran temporalmente y se eliminan del repositorio
  mediante una tarea de caducidad cada segundo, incluso sin una página abierta.
  El contexto previo no se copia al evento persistente.
- AMBIGUO se considera relevante para revisión de la demo: conserva sólo su frase
  y evaluación en el historial, limitado a 100 eventos, y no genera archivo.
- La evidencia (`EvidenceEvent`, transcripción, análisis, hashes, fotos, personas del
  evento y estado de revisión) se guarda en la base local `data/nexo.db` y sobrevive a un
  reinicio; los archivos WAV, MP4 y JPG permanecen en `evidence/`.
- La bitácora conserva identificador, clasificación, prioridad y acciones, sin
  copiar conversaciones normales. Las cuentas continúan siendo de demostración.
- Por defecto el proveedor es local; cambiar `AI_CONTEXT_URL` a un servidor remoto
  implica enviarle contexto y frase. Ese proveedor deberá implementar su propia
  política de retención antes de utilizar conversaciones reales.

### Verificación

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`tests/test_alert_import.py` cubre la importación de alertas: validación del
archivo, lectura tolerante de etiquetas pegadas, formatos de fecha, lectura real de
una ficha sintética con el motor instalado, corrección manual de campos,
comparación textual y contextual, la preparación facial sin niveles inventados, el
alta y vínculo de casos, la cancelación con borrado de temporales y los permisos.

`tests/test_assistant.py` cubre además el asistente administrativo: las veinte
frases de ejemplo hacia sus intenciones, la ejecución de cada comando, el rechazo
de intenciones sensibles, la restricción por rol, la elección manual entre varias
personas, la bitácora y el contrato del proveedor de IA con transporte simulado.

Incluye los escenarios semánticos solicitados y las ocho pruebas del módulo de
evidencia: narración pasada sin evidencia, rechazo tras conversación ordinaria,
solicitud actual con audio protegido, prioridad alta con cambio acústico, falso
positivo, solicitud de eliminación, rechazo y aprobación por un supervisor
distinto. También cubre buffer circular, unicidad de archivos, verificación
SHA-256, el punto de integración de video y el recorrido de la interfaz.
Los tests acústicos usan arrays sintéticos; no validan emociones ni peligro real.
