"""Face detection and 512-number face embeddings with InsightFace.

This is the only module that talks to InsightFace. The model is loaded once, lazily and
thread-safely, the first time a face is analysed. A similarity is a lead for a person to
review, never an identity.

Download the model and run the self-check with:  python -m services.face_engine
Live webcam check (R registers a face, Q quits):   python -m services.face_engine --camara
"""
import base64
import importlib.util
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import config

ENGINE_NAME = f'InsightFace {config.FACE_MODEL}'
# Only these tasks are loaded; the 3D and 106-point landmark models are not needed.
MODULES = ['detection', 'recognition', 'genderage']
RASTER_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
# A mirrored copy of the same face scores ~0.97 with buffalo_l.
SELF_CHECK_SAME_PERSON = 0.80

# scikit-image 0.26 deprecates a call InsightFace 2.0 still makes; the result is identical.
warnings.filterwarnings('ignore', category=FutureWarning, module=r'insightface\.utils\.face_align')

_load_lock = threading.Lock()
_inference_lock = threading.Lock()
_app = None


class FaceEngineUnavailable(RuntimeError):
    """InsightFace or its model cannot be used on this computer."""


@dataclass
class FaceResult:
    bbox: tuple  # x1, y1, x2, y2 in pixels
    det_score: float  # detector confidence, 0-1
    embedding: np.ndarray  # 512 float32 values, L2-normalised
    age: int | None = None  # approximate; useful to sort, never to discard

    @property
    def area(self):
        x1, y1, x2, y2 = self.bbox
        return max(0, x2 - x1) * max(0, y2 - y1)


def installed():
    return importlib.util.find_spec('insightface') is not None


def model_dir():
    return Path(config.FACE_MODEL_ROOT) / 'models' / config.FACE_MODEL


def model_downloaded():
    folder = model_dir()
    return folder.is_dir() and any(folder.glob('*.onnx'))


def download_progress():
    """MB ya descargados mientras el modelo se baja por primera vez; None si no se está bajando.

    InsightFace escribe el ZIP en la carpeta de modelos y lo descomprime al terminar: su tamaño
    es el avance que ve quien espera.
    """
    if model_downloaded():
        return None
    try:
        return (Path(config.FACE_MODEL_ROOT) / 'models' / f'{config.FACE_MODEL}.zip').stat().st_size / 1_048_576
    except OSError:
        return None


def loaded():
    """True cuando el modelo ya está en memoria: analizar una foto tarda sólo milisegundos."""
    return _app is not None


def ready():
    """True cuando se puede analizar sin descargar nada: el modelo ya está en memoria o en disco.

    Los procesos de fondo (cotejo automático con fichas, perfiles) lo consultan antes de
    calcular huellas, para no disparar la descarga de ~330 MB en un momento inesperado.
    """
    return _app is not None or (installed() and model_downloaded())


def status():
    """Diagnostics for the interface and the command line; it never loads the model."""
    return {'engine': ENGINE_NAME, 'installed': installed(), 'model_downloaded': model_downloaded(),
            'loaded': _app is not None, 'model_dir': str(model_dir())}


def load(download=None):
    """Shared FaceAnalysis instance. Downloads the model when allowed (FACE_AUTO_DOWNLOAD)."""
    global _app
    if _app is not None:
        return _app
    with _load_lock:
        if _app is None:
            if not installed():
                raise FaceEngineUnavailable('InsightFace no está instalado. Ejecuta: '
                                            'python -m pip install -r requirements.txt')
            allowed = config.FACE_AUTO_DOWNLOAD if download is None else download
            if not model_downloaded() and not allowed:
                raise FaceEngineUnavailable('Falta el modelo facial. Ejecuta: python -m services.face_engine')
            try:
                from insightface.app import FaceAnalysis
                # Without explicit providers InsightFace picks CUDA or CoreML when present, else CPU.
                app = FaceAnalysis(name=config.FACE_MODEL, root=str(config.FACE_MODEL_ROOT),
                                   allowed_modules=MODULES)
                app.prepare(ctx_id=0, det_thresh=config.FACE_MIN_DET_SCORE)
            except Exception as error:
                if not model_downloaded():  # casi siempre, sin conexión a internet
                    raise FaceEngineUnavailable('No se pudo descargar el modelo facial. Revisa la conexión a '
                                                'internet; NEXO lo vuelve a intentar solo.') from error
                raise FaceEngineUnavailable(f'No fue posible cargar el modelo facial: {error}') from error
            _app = app
            # InsightFace deja el ZIP junto a la carpeta ya descomprimida: ~275 MB que no se vuelven
            # a usar (sólo se descarga de nuevo si falta la carpeta).
            try:
                (Path(config.FACE_MODEL_ROOT) / 'models' / f'{config.FACE_MODEL}.zip').unlink(missing_ok=True)
            except OSError:
                pass
    return _app


def read_image(source):
    """BGR image from an array, bytes, a data URL or a path; None if it is not a raster image.

    Relative paths and web paths such as /assets/... resolve against the project folder.
    Bytes are decoded in memory, so paths with accents also work on Windows.
    """
    if isinstance(source, np.ndarray):
        return source
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
    elif isinstance(source, str) and source.startswith('data:'):
        try:
            data = base64.b64decode(source.split(',', 1)[1])
        except (IndexError, ValueError):
            return None
    else:
        path = Path(source)
        if not path.is_absolute():
            path = config.BASE_DIR / str(source).lstrip('/\\')
        if path.suffix.lower() not in RASTER_SUFFIXES or not path.is_file():
            return None
        data = path.read_bytes()
    if not data:
        return None
    import cv2
    return cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)


def analyze(image):
    """Every face in the image, most prominent first (size × detector confidence)."""
    pixels = read_image(image)
    if pixels is None:
        return []
    app = load()
    with _inference_lock:
        faces = app.get(pixels)
    results = [FaceResult(bbox=tuple(int(value) for value in face.bbox), det_score=float(face.det_score),
                          embedding=np.asarray(face.normed_embedding, dtype=np.float32),
                          age=int(face.age) if face.age is not None else None)
               for face in faces if face.embedding is not None]
    return sorted(results, key=lambda face: face.area * face.det_score, reverse=True)


def best_face(image):
    """The most prominent face, or None when the image has no detectable face."""
    faces = analyze(image)
    return faces[0] if faces else None


def similarity(first, second):
    """Cosine similarity between two embeddings, from -1 to 1."""
    a, b = np.asarray(first, dtype=np.float32), np.asarray(second, dtype=np.float32)
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / norm) if norm else 0.0


def level_of(value):
    """ALTA, MEDIA o BAJA desde el umbral de propuesta hacia arriba; None debajo."""
    if value >= config.FACE_LEVEL_HIGH:
        return 'ALTA'
    if value >= config.FACE_LEVEL_MEDIUM:
        return 'MEDIA'
    if value >= config.FACE_MATCH_THRESHOLD:
        return 'BAJA'
    return None


def display_level(percent):
    """Para pantalla: convierte un porcentaje guardado (0-100) en ALTA/MEDIA/BAJA.

    La interfaz nunca debe mostrar el porcentaje crudo junto a un nombre o caso antes de
    que una persona lo revise: un «72 %» se lee como una identificación, aunque no lo sea.
    """
    if percent is None:
        return 'SIN NIVEL'
    return level_of(percent / 100) or 'SIN NIVEL'


# ------------------------------------------------------------------ command line
def self_check():
    """Same face mirrored must match; different people in the sample must not."""
    from insightface.data import get_image
    sample = get_image('t1')
    faces = analyze(sample)
    if len(faces) < 2:
        return False, f'Se esperaban varios rostros en la imagen de ejemplo y se detectaron {len(faces)}.'
    mirrored = analyze(sample[:, ::-1].copy())
    same = max((similarity(faces[0].embedding, face.embedding) for face in mirrored), default=0.0)
    others = max(similarity(faces[i].embedding, faces[j].embedding)
                 for i in range(len(faces)) for j in range(i + 1, len(faces)))
    passed = same >= SELF_CHECK_SAME_PERSON and others < config.FACE_MATCH_THRESHOLD
    return passed, (f'{len(faces)} rostros · misma persona {same:.2f} · '
                    f'personas distintas máx. {others:.2f} (umbral {config.FACE_MATCH_THRESHOLD:.2f})')


CAMERA_WINDOW = 'NEXO - prueba de camara'
# BGR colours by level. Faces below the threshold stay grey: most people in view are nobody's case.
LEVEL_COLORS = {'ALTA': (80, 175, 76), 'MEDIA': (0, 200, 255), 'BAJA': (0, 140, 255), None: (170, 170, 170)}


def draw_overlay(frame, faces, target):
    """Boxes, similarity with the reference and a hint line. OpenCV text is ASCII only."""
    import cv2
    dark = frame.mean() < 5
    for face in faces:
        if target is None:
            color, label = (255, 255, 255), 'Pulsa R para registrar'
        else:
            value = similarity(target.embedding, face.embedding)
            level = level_of(value)
            color, label = LEVEL_COLORS[level], f'{value:.0%} {level or "sin coincidencia"}'
        x1, y1, x2, y2 = face.bbox
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, max(24, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, .7, color, 2)
    if dark:
        hint = 'Imagen negra: destapa la camara o agrega luz'
    elif not faces:
        hint = 'Sin rostros: colocate de frente a la camara'
    else:
        hint = ('R: registrar rostro' if target is None else 'R: cambiar referencia') + '   Q: salir'
    for color, width in (((0, 0, 0), 4), ((255, 255, 255), 1)):  # outlined, readable on any background
        cv2.putText(frame, hint, (12, frame.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, .6, color, width)


def live_camera(index=0, reference=None):
    """Live check with the webcam: every face is boxed and compared with the reference.

    Frames are only analysed in memory; nothing is saved to disk.
    """
    import cv2
    target = best_face(reference) if reference else None
    if reference and target is None:
        print(f'ERROR: no se detectó un rostro en {reference}.')
        return 1
    # DirectShow opens in about a second on Windows; the default backend can take several.
    camera = cv2.VideoCapture(index, cv2.CAP_DSHOW if sys.platform == 'win32' else cv2.CAP_ANY)
    if not camera.isOpened():
        print(f'ERROR: no se pudo abrir la cámara {index}. Ciérrala en otras aplicaciones y revisa '
              'Configuración > Privacidad y seguridad > Cámara.')
        return 1
    print('Cámara abierta. En la ventana: R registra el rostro más visible como referencia; Q o Esc salen.')
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                print('ERROR: la cámara dejó de enviar imágenes.')
                return 1
            frame = cv2.flip(frame, 1)  # mirror view, as people expect from a webcam
            faces = analyze(frame)
            draw_overlay(frame, faces, target)
            cv2.imshow(CAMERA_WINDOW, frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q'), 27) or cv2.getWindowProperty(CAMERA_WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                return 0
            if key in (ord('r'), ord('R')) and faces:
                target = faces[0]
                print('Referencia registrada con el rostro más visible.')
    except KeyboardInterrupt:
        return 0
    finally:
        camera.release()
        cv2.destroyAllWindows()


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog='python -m services.face_engine',
                                     description='Descarga el modelo facial y comprueba que funciona.')
    parser.add_argument('--imagen', help='analiza esta imagen en lugar de la autoprueba')
    parser.add_argument('--camara', nargs='?', type=int, const=0, metavar='N',
                        help='prueba en vivo con la webcam N (0 si se omite)')
    parser.add_argument('--referencia', help='con --camara: foto con la que se compara el rostro en vivo')
    args = parser.parse_args(argv)
    info = status()
    print(f'Motor: {ENGINE_NAME}')
    print(f'InsightFace instalado: {"sí" if info["installed"] else "no"}')
    print(f'Modelo: {info["model_dir"]} ({"descargado" if info["model_downloaded"] else "se descargará ahora"})')
    started = time.perf_counter()
    try:
        load(download=True)
    except FaceEngineUnavailable as error:
        print(f'ERROR: {error}')
        return 1
    print(f'Modelo cargado en {time.perf_counter() - started:.1f} s')
    if args.camara is not None:
        return live_camera(args.camara, args.referencia)
    if args.imagen:
        started = time.perf_counter()
        faces = analyze(args.imagen)
        print(f'Rostros detectados: {len(faces)} en {time.perf_counter() - started:.2f} s')
        for number, face in enumerate(faces, 1):
            print(f'  {number}. confianza {face.det_score:.2f} · edad aprox. {face.age} · '
                  f'huella de {face.embedding.size} números')
        return 0 if faces else 1
    passed, detail = self_check()
    print(f'Autoprueba: {"OK" if passed else "FALLÓ"} · {detail}')
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
