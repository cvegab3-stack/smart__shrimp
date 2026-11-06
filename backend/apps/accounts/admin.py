"""Registro de modelos de acceso en el panel Django."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.core.exceptions import PermissionDenied, ValidationError

from .models import AuditEvent, User
from .services import LAST_ADMIN_MESSAGE, leaves_without_administrator


class ProtectedUserChangeForm(UserChangeForm):
    """El panel /admin/ aplica la misma regla que la API: siempre queda un administrador activo."""

    class Meta(UserChangeForm.Meta):
        model = User

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk and leaves_without_administrator(
                self.instance, role=cleaned.get("role"), is_active=cleaned.get("is_active")):
            raise ValidationError(LAST_ADMIN_MESSAGE)
        return cleaned


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Administra usuarios desde Django con su rol SMART SHRIMP."""

    form = ProtectedUserChangeForm

    list_display = ("username", "email", "role", "is_active", "is_staff")
    fieldsets = DjangoUserAdmin.fieldsets + (("SMART SHRIMP", {"fields": ("role", "failed_login_attempts", "locked_until")}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (("SMART SHRIMP", {"fields": ("role",)}),)

    def has_delete_permission(self, request, obj=None):
        # No se puede borrar al último administrador activo (ni en lote: la acción respeta este permiso por objeto).
        if obj is not None and leaves_without_administrator(obj, is_active=False):
            return False
        return super().has_delete_permission(request, obj)

    def delete_queryset(self, request, queryset):
        remaining = User.objects.filter(role=User.Role.ADMINISTRATOR, is_active=True).exclude(pk__in=queryset)
        if not remaining.exists():  # borrado en lote de todos los administradores: se rechaza entero
            raise PermissionDenied(LAST_ADMIN_MESSAGE)
        super().delete_queryset(request, queryset)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    """Muestra bitácora en modo solo lectura."""

    list_display = ("created_at", "actor_id", "action", "ip_address")
    list_filter = ("action", "created_at")
    readonly_fields = ("actor_id", "action", "details", "ip_address", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
