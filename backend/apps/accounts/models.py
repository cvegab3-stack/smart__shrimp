"""Modelos de identidad y bitácora de eventos."""

from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.db import models


class UserManager(DjangoUserManager):
    """Administrador creado desde CLI recibe el rol de negocio adecuado."""

    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault("role", "administrador")
        return super().create_superuser(username, email, password, **extra_fields)


class User(AbstractUser):
    """Usuario autenticable con rol de negocio y control temporal de bloqueo."""

    class Role(models.TextChoices):
        OPERATOR = "operador", "Operador"
        QUALITY = "control_calidad", "Control de calidad"
        SUPERVISOR = "supervisor", "Supervisor"
        ADMINISTRATOR = "administrador", "Administrador"

    role = models.CharField(max_length=24, choices=Role.choices, default=Role.OPERATOR)
    failed_login_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    objects = UserManager()


class ImmutableAuditQuerySet(models.QuerySet):
    """Impide las operaciones de mutación masiva sobre la bitácora."""

    def update(self, **kwargs):
        raise TypeError("La bitácora es inmutable.")

    def delete(self):
        raise TypeError("La bitácora es inmutable.")


class AuditEvent(models.Model):
    """Evento de seguridad o acción autorizada, conservado sin FK mutable."""

    actor_id = models.PositiveBigIntegerField(null=True, blank=True)
    action = models.CharField(max_length=80)
    details = models.JSONField(default=dict)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = ImmutableAuditQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at", "-pk")

    def save(self, *args, **kwargs):
        if self.pk and AuditEvent.objects.filter(pk=self.pk).exists():
            raise TypeError("La bitácora es inmutable.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise TypeError("La bitácora es inmutable.")
