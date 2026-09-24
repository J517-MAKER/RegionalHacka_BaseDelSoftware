"""Evidence lifecycle: immutable audio, integrity hash, human review and deletion control."""
import hashlib
import threading
import wave
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4
import config
from models.deletion_request import DeletionRequest
from models.evidence_event import EvidenceEvent
from services import store
from services.users_service import require

_id_lock = threading.Lock()


def ensure_directories():
    for directory in (config.EVIDENCE_AUDIO_DIR, config.EVIDENCE_VIDEO_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    return config.EVIDENCE_DIR


def next_event_id(when=None):
    """Sequential, collision-free identifier. Never reuses an id already on disk."""
    day = (when or datetime.now()).strftime('%Y%m%d')
    ensure_directories()
    with _id_lock:
        used = {e.event_id for e in store.evidence}
        used |= {p.stem for p in config.EVIDENCE_AUDIO_DIR.glob('EVENT-' + day + '-*.wav')}
        number = 1
        while f'EVENT-{day}-{number:05d}' in used:
            number += 1
        return f'EVENT-{day}-{number:05d}'


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(65536), b''):
            digest.update(block)
    return digest.hexdigest()


def write_audio(event_id, samples, sample_rate=None):
    """Write the original fragment once. An existing file is never overwritten."""
    import numpy as np
    ensure_directories()
    rate = sample_rate or config.AUDIO_SAMPLE_RATE
    path = config.EVIDENCE_AUDIO_DIR / (event_id + '.wav')
    if path.exists():
        raise ValueError('Ya existe un archivo de evidencia con ese identificador.')
    data = np.clip(np.asarray(samples, dtype=np.float32).reshape(-1), -1, 1)
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((data * 32767).astype('<i2').tobytes())
    return path, file_hash(path), len(data) / rate


def project_path(path):
    """Store a path relative to the project when possible, so evidence stays portable."""
    try:
        return Path(path).relative_to(config.BASE_DIR).as_posix()
    except ValueError:
        return Path(path).as_posix()


def create_evidence(voice_event, risk, samples, started_at, ended_at, sample_rate=None, actor='Sistema'):
    """Called by the detection pipeline; evidence is never created by hand from the interface."""
    event_id = next_event_id()
    path, digest, duration = write_audio(event_id, samples, sample_rate)
    semantic, acoustic = risk.semantic_analysis, risk.acoustic_summary
    evidence = EvidenceEvent(
        event_id=event_id, camera_id=voice_event.camera_id, location=voice_event.location,
        created_at=store.now(), classification=risk.classification, priority=risk.priority,
        audio_file=project_path(path),
        audio_start_timestamp=started_at, audio_end_timestamp=ended_at, audio_duration=round(duration, 1),
        transcript_original=voice_event.text_original, transcript_normalized=voice_event.text_normalized,
        transcript_segments=(voice_event.recognition_metadata or {}).get('segments', []),
        semantic_analysis=semantic.model_dump(), acoustic_analysis=asdict(acoustic), assessment=risk,
        integrity_hash=digest, voice_event_id=voice_event.id)
    store.evidence.insert(0, evidence)
    voice_event.evidence_id = event_id
    store.audit(actor, 'Evidencia',
                f'{event_id} creado automáticamente. Audio protegido (SHA-256 {digest[:12]}).',
                camera_id=evidence.camera_id, result='PENDIENTE_REVISION')
    return evidence


def get_evidence():
    return store.evidence


def get_event(event_id):
    return next((e for e in store.evidence if e.event_id == event_id), None)


def require_event(event_id):
    event = get_event(event_id)
    if not event:
        raise ValueError('No se encontró la evidencia solicitada.')
    return event


def verify_integrity(event):
    """True only when the original file still matches the hash stored at creation."""
    path = config.BASE_DIR / event.audio_file
    if not event.audio_file or not path.exists() or not event.integrity_hash:
        return False
    return file_hash(path) == event.integrity_hash


def register_playback(event_id):
    actor = require('evidence.play')
    event = require_event(event_id)
    store.audit(actor, 'Evidencia', f'{actor} reprodujo evidencia {event.event_id}.',
                camera_id=event.camera_id, result='Consulta')
    return event


REVIEW_ACTIONS = {'CONFIRMADO_PARA_ATENCION': 'confirmó que requiere atención',
                  'FALSO_POSITIVO': 'marcó como falso positivo',
                  'EN_REVISION': 'envió a revisión'}


def _sync_alert(event):
    """Keep the monitoring views aligned with the review state of the evidence."""
    alert = next((a for a in store.alerts if a.voice_event_id == event.voice_event_id), None)
    if alert:
        alert.status = event.review_status
        alert.reviewed_by, alert.reviewed_at = event.reviewed_by or '', event.reviewed_at or ''
    voice_event = next((v for v in store.voice_events if v.id == event.voice_event_id), None)
    if voice_event:
        voice_event.status = event.review_status


def review_event(event_id, status, notes=''):
    """Changes only the review state. The stored audio is never modified."""
    actor = require('alerts.review')
    event = require_event(event_id)
    if status not in REVIEW_ACTIONS:
        raise ValueError('Estado de revisión no válido.')
    if event.review_status in ('DELETION_REQUESTED', 'DELETION_APPROVED'):
        raise ValueError('La evidencia tiene una solicitud de eliminación en curso.')
    event.review_status, event.reviewed_by, event.reviewed_at = status, actor, store.now()
    event.review_notes = notes or event.review_notes
    _sync_alert(event)
    store.audit(actor, 'Revisión', f'{actor} {REVIEW_ACTIONS[status]} {event.event_id}.',
                camera_id=event.camera_id, result=status)
    return event


def request_deletion(event_id, reason):
    """An operator may ask; only a different supervisor may authorise. Nothing is erased."""
    actor = require('deletion.request')
    event = require_event(event_id)
    reason = (reason or '').strip()
    if len(reason) < 5:
        raise ValueError('Describe el motivo de la solicitud (al menos 5 caracteres).')
    if any(r.event_id == event_id and r.status == 'PENDING' for r in store.deletion_requests):
        raise ValueError('Ya existe una solicitud pendiente para esta evidencia.')
    request = DeletionRequest('DEL-' + uuid4().hex[:8].upper(), event_id, actor, store.now(),
                              reason[:500], integrity_hash=event.integrity_hash)
    store.deletion_requests.insert(0, request)
    event.review_status = 'DELETION_REQUESTED'
    _sync_alert(event)
    store.audit(actor, 'Evidencia', f'{actor} solicitó eliminación de {event.event_id}. Motivo: {request.reason}',
                camera_id=event.camera_id, result='DELETION_REQUESTED')
    return request


def get_deletion_requests(status=None):
    return [r for r in store.deletion_requests if status is None or r.status == status]


def resolve_deletion(request_id, approve, notes=''):
    actor = require('deletion.approve')
    request = next((r for r in store.deletion_requests if r.request_id == request_id), None)
    if not request or request.status != 'PENDING':
        raise ValueError('La solicitud no existe o ya fue resuelta.')
    if request.requested_by == actor:
        raise ValueError('La solicitud debe ser autorizada por una persona distinta a quien la solicitó.')
    event = require_event(request.event_id)
    request.status = 'APPROVED' if approve else 'REJECTED'
    request.reviewed_by, request.reviewed_at, request.resolution_notes = actor, store.now(), (notes or '')[:500]
    # Prototype: an approval marks the evidence; the original file is not erased.
    event.review_status = 'DELETION_APPROVED' if approve else 'DELETION_REJECTED'
    _sync_alert(event)
    verb = 'aprobó' if approve else 'rechazó'
    store.audit(actor, 'Evidencia',
                f'{actor} {verb} la solicitud {request.request_id} de {request.requested_by} sobre {event.event_id}. '
                f'Motivo: {request.reason}. SHA-256 {request.integrity_hash[:12]}',
                camera_id=event.camera_id, result=event.review_status)
    return request


def attach_video_evidence(event_id, video_path, start_timestamp, end_timestamp):
    """Integration point for the camera module. Audio and video share the same event_id."""
    event = require_event(event_id)
    path = Path(video_path)
    if not path.is_absolute():
        path = config.BASE_DIR / path
    if not path.exists():
        raise ValueError('No se encontró el archivo de video indicado.')
    event.video_file = project_path(path)
    event.video_start_timestamp, event.video_end_timestamp = start_timestamp, end_timestamp
    event.video_status = 'ATTACHED'
    store.audit('Sistema', 'Evidencia', f'Video asociado a {event.event_id}.',
                camera_id=event.camera_id, result='ATTACHED')
    return event
