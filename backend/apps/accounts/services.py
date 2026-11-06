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


def authenticate_user(username: str, password: str, ip_address: str | None = None,
                      expected_role: str | None = None) -> tuple[User | None, str | None]:
    """Verifica contraseña y aplica bloqueo tras tres intentos fallidos.

    Una cuenta inactiva con la contraseña correcta devuelve "account_inactive" sin sumar intento fallido; con una
    contraseña incorrecta recibe el error genérico, para no revelar su estado a quien no conoce la contraseña.

    Con `expected_role` (perfil elegido en la pantalla de acceso), una cuenta de otro rol se rechaza igual que una
    contraseña incorrecta: cuenta como intento fallido y devuelve el mismo error, para no revelar que la contraseña
    era válida. La bitácora sí distingue el caso (login.role_mismatch).
    """
    with transaction.atomic():
        # El usuario no distingue mayúsculas ("inspector" entra a "Inspector"). Si por datos antiguos hubiera dos
        # cuentas que solo difieren en mayúsculas, se exige la coincidencia exacta para no entrar a la equivocada.
        candidates = list(User.objects.select_for_update().filter(username__iexact=username)[:2])
        user = next((c for c in candidates if c.username == username), candidates[0] if len(candidates) == 1 else None)
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
        valid_password = user.check_password(password)
        if valid_password and not user.is_active:
            # Solo quien conoce la contraseña sabe que la cuenta está inactiva; no cuenta como intento fallido.
            record_event("login.inactive", user, ip_address=ip_address)
            return None, "account_inactive"
        role_mismatch = valid_password and expected_role is not None and user.role != expected_role
        if not valid_password or role_mismatch:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= LOCK_AFTER_FAILURES:
                user.locked_until = now + LOCK_DURATION
                record_event("login.account_locked", user, {"duration_minutes": 15}, ip_address)
            elif role_mismatch:
                record_event("login.role_mismatch", user, {"expected_role": expected_role}, ip_address)
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


PASSWORD_EVENTS = ("password.changed_by_user", "password.reset_by_admin")


@transaction.atomic
def change_own_password(user: User, new_password: str, ip_address: str | None = None) -> User:
    """El propio usuario cambia su contraseña (la actual ya fue verificada por el formulario)."""
    validate_password(new_password, user)
    user.set_password(new_password)
    user.save(update_fields=("password",))
    record_event("password.changed_by_user", user, {"user_id": user.pk}, ip_address)
    return user


@transaction.atomic
def set_user_password(user: User, new_password: str, *, actor: User, ip_address: str | None = None) -> User:
    """El administrador asigna una contraseña nueva a cualquier cuenta y la desbloquea.

    La bitácora guarda quién la cambió y a qué cuenta; nunca la contraseña.
    """
    validate_password(new_password, user)
    user.set_password(new_password)
    user.failed_login_attempts = 0
    user.locked_until = None
    user.save(update_fields=("password", "failed_login_attempts", "locked_until"))
    record_event("password.reset_by_admin", actor, {"user_id": user.pk}, ip_address)
    return user


def password_changes() -> dict[int, dict]:
    """Último cambio de contraseña por cuenta, leído de la bitácora: {user_id: {at, by, actor}}."""
    latest: dict[int, AuditEvent] = {}
    for event in AuditEvent.objects.filter(action__in=PASSWORD_EVENTS).order_by("created_at", "pk"):
        user_id = (event.details or {}).get("user_id")
        if user_id is not None:
            latest[user_id] = event
    actors = dict(User.objects.filter(pk__in={e.actor_id for e in latest.values()}).values_list("pk", "username"))
    return {
        user_id: {
            "at": event.created_at,
            "by": "usuario" if event.action == "password.changed_by_user" else "administrador",
            "actor": actors.get(event.actor_id),
        }
        for user_id, event in latest.items()
    }


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
