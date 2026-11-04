"""Permisos por rol con registro de denegaciones."""

from functools import wraps

from django.core.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .models import User
from .services import record_event


class RolePermission(BasePermission):
    """Autoriza una vista cuando el usuario autenticado tiene el rol requerido."""

    allowed_roles: tuple[str, ...] = ()

    def has_permission(self, request, view) -> bool:
        user = request.user
        if user and user.is_authenticated and user.role in self.allowed_roles:
            return True
        record_event(
            "permission.denied",
            actor=user if user and user.is_authenticated else None,
            details={"path": request.path, "method": request.method, "required_roles": list(self.allowed_roles)},
            ip_address=request.META.get("REMOTE_ADDR"),
        )
        return False


class AdministratorOnly(RolePermission):
    """Permite únicamente al administrador (cuentas, calibración y umbrales)."""

    allowed_roles = (User.Role.ADMINISTRATOR,)


class OperatorOnly(RolePermission):
    """Permite iniciar y procesar análisis al operador."""

    allowed_roles = (User.Role.OPERATOR,)


class SupervisorOnly(RolePermission):
    """Limita reportes y descargas al supervisor."""

    allowed_roles = (User.Role.SUPERVISOR,)


class OperationalRoles(RolePermission):
    """Permite consultar análisis e historial a operador, control de calidad y supervisor."""

    allowed_roles = (User.Role.OPERATOR, User.Role.QUALITY, User.Role.SUPERVISOR)


def role_required(*roles: str):
    """Equivalente HTML de RolePermission: registra la denegación y responde 403 (usar tras login_required)."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                record_event("permission.denied", request.user, {"path": request.path, "method": request.method},
                             request.META.get("REMOTE_ADDR"))
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
