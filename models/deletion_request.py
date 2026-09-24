from dataclasses import dataclass


@dataclass
class DeletionRequest:
    request_id: str
    event_id: str
    requested_by: str
    requested_at: str
    reason: str
    status: str = 'PENDING'
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    resolution_notes: str = ''
    integrity_hash: str = ''
