"""Casos de uso de cuentas, autenticación y bitácora."""

from datetime import timedelta

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
from django.utils import timezone

from .models import AuditEvent, User

LOCK_AFTER_FAILURES = 3
LOCK_DURATION = timedelta(minutes=15)


def record_event(action: str, actor: User | None = None, details: dict | None = None, ip_address: str | None = None) -> AuditEvent:
    """Persiste un evento de auditoría sin datos de credenciales."""
    return AuditEvent.objects.create(
        actor_id=actor.pk if actor and actor.pk else None,
        action=action,
        details=details or {},
        ip_address=ip_address or None,
    )


def authenticate_user(username: str, password: str, ip_address: str | None = None) -> tuple[User | None, str | None]:
    """Verifica contraseña y aplica bloqueo tras tres intentos fallidos."""
    with transaction.atomic():
        user = User.objects.select_for_update().filter(username=username).first()
        if user is None:
            record_event("login.failed", details={"username": username}, ip_address=ip_address)
            return None, "invalid_credentials"
        now = timezone.now()
        if user.locked_until and user.locked_until > now:
            record_event("login.locked", user, ip_address=ip_address)
            return None, "account_locked"
        if user.locked_until:
            user.locked_until = None
            user.failed_login_attempts = 0
        if not user.is_active or not user.check_password(password):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= LOCK_AFTER_FAILURES:
                user.locked_until = now + LOCK_DURATION
                record_event("login.account_locked", user, {"duration_minutes": 15}, ip_address)
            else:
                record_event("login.failed", user, ip_address=ip_address)
            user.save(update_fields=("failed_login_attempts", "locked_until"))
            return None, "invalid_credentials"
        user.failed_login_attempts = 0
        user.locked_until = None
        user.save(update_fields=("failed_login_attempts", "locked_until"))
        record_event("login.succeeded", user, ip_address=ip_address)
        return user, None


@transaction.atomic
def create_user(*, username: str, password: str, role: str, first_name: str = "", last_name: str = "", email: str = "", actor: User | None = None, ip_address: str | None = None) -> User:
    """Crea una cuenta con contraseña validada y hash administrado por Django."""
    if role not in User.Role.values:
        raise ValueError("Rol de usuario no válido.")
    user = User(username=username, role=role, first_name=first_name, last_name=last_name, email=email)
    validate_password(password, user)
    user.set_password(password)
    user.save()
    record_event("user.created", actor, {"user_id": user.pk, "role": user.role}, ip_address)
    return user


@transaction.atomic
def update_user(user: User, *, role: str | None = None, is_active: bool | None = None, actor: User | None = None, ip_address: str | None = None) -> User:
    """Actualiza el rol o estado de una cuenta y deja evidencia de la acción."""
    changed: list[str] = []
    if role is not None:
        if role not in User.Role.values:
            raise ValueError("Rol de usuario no válido.")
        user.role = role
        changed.append("role")
    if is_active is not None:
        user.is_active = is_active
        changed.append("is_active")
    if changed:
        user.save(update_fields=changed)
        record_event("user.updated", actor, {"user_id": user.pk, "fields": changed}, ip_address)
    return user
