"""Re-identificación de personas por apariencia. Punto de integración, todavía sin modelo.

Permitiría comparar a una persona cuando su rostro no es visible, usando ropa, complexión
y accesorios. Aquí sólo existe la interfaz: no se entrena ni se ejecuta ningún modelo, y
ninguna función devuelve una similitud inventada.

La apariencia es evidencia complementaria. Nunca sustituye al rostro ni basta por sí sola,
y no debe usarse para inferir atributos sensibles de una persona desde una imagen.
"""

STATUS_PENDING = 'PENDIENTE_INTEGRACION'


def available():
    """True cuando exista un modelo real de Re-ID integrado."""
    return False


def status():
    return {'available': available(), 'status': STATUS_PENDING,
            'message': 'Módulo de re-identificación por apariencia pendiente de integración.'}


def appearance_embedding(image_path):
    """Huella de apariencia de una persona recortada. None mientras no haya modelo."""
    return None


def compare(first, second):
    """Similitud de apariencia entre dos huellas.

    Devuelve NO_EVALUABLE mientras el módulo no exista: la ausencia de comparación no
    penaliza a un candidato, sólo significa que no había con qué compararlo.
    """
    return {'level': 'NO_EVALUABLE', 'score': None, 'status': STATUS_PENDING,
            'detail': 'Comparación por apariencia pendiente de integración.'}
