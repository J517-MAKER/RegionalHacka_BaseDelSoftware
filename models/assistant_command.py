from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

Intent = Literal['OPEN_CASE', 'SEARCH_PERSON', 'SHOW_LAST_DETECTION', 'SHOW_MATCHES',
                 'OPEN_CAMERA', 'SHOW_ALERTS', 'SHOW_PENDING_ALERTS', 'UNKNOWN_COMMAND']

# The assistant only queries, opens and navigates. Nothing here modifies data.
READ_ONLY_INTENTS = frozenset(Intent.__args__)


class AssistantCommand(BaseModel):
    """Structured interpretation of an administrative voice command."""
    model_config = ConfigDict(extra='forbid', strict=True)
    intent: Intent
    folio: str | None = Field(default=None, max_length=32)
    person: str | None = Field(default=None, max_length=80)
    camera: str | None = Field(default=None, max_length=32)
    mode: Literal['IA contextual', 'Reglas locales'] = 'Reglas locales'

    @property
    def parameters(self):
        return {key: value for key, value in
                (('folio', self.folio), ('person', self.person), ('camera', self.camera)) if value}
