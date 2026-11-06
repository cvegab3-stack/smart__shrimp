"""Manejo de errores de la API compartido por todas las apps."""

from rest_framework import exceptions, status
from rest_framework.views import exception_handler as drf_exception_handler

SESSION_EXPIRED_MESSAGE = "Tu sesión expiró. Vuelve a iniciar sesión."


def exception_handler(exc, context):
    """Igual que el de DRF, pero una petición sin sesión responde 401 con code "session_expired".

    Con autenticación por sesión DRF devuelve 403 tanto si falta la sesión como si falta el permiso; así la página
    puede llevar al acceso solo cuando la sesión venció, y seguir mostrando "sin permiso" en el otro caso.
    """
    response = drf_exception_handler(exc, context)
    if response is not None and isinstance(exc, exceptions.NotAuthenticated):
        response.status_code = status.HTTP_401_UNAUTHORIZED
        response.data = {"detail": SESSION_EXPIRED_MESSAGE, "code": "session_expired"}
    return response
