from dataclasses import dataclass, field


@dataclass
class Person:
    name: str
    age: str = 'Desconocida'
    sex: str = 'Desconocido'
    height: str = 'Desconocida'
    build: str = 'Desconocida'
    skin: str = 'Desconocido'
    hair: str = 'Desconocido'
    eyes: str = 'Desconocido'
    clothing: str = 'Sin información'
    marks: str = 'Sin información'
    description: str = ''
    photos: list[str] = field(default_factory=list)
