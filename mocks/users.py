from models.user import User


def seed_users():
    return [User('USR-01','Andrea Montes · demo','Operador01','Operador','2026-09-23 08:00'),
            User('USR-02','Luis Santos · demo','Operador02','Operador','2026-09-23 08:30'),
            User('USR-03','Sofía Campos · demo','Supervisor01','Supervisor','2026-09-23 07:50'),
            User('USR-04','Administración · demo','Admin01','Administrador','2026-09-23 07:00')]
