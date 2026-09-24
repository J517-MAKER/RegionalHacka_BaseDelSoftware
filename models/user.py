from dataclasses import dataclass


@dataclass
class User:
    id: str
    name: str
    username: str
    role: str
    last_access: str
    status: str = 'Activo'
