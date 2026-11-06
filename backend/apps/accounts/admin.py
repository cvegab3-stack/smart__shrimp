"""Registro de modelos de acceso en el panel Django."""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AuditEvent, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Administra usuarios desde Django con su rol SMART SHRIMP."""

    list_display = ("username", "email", "role", "is_active", "is_staff")
    fieldsets = DjangoUserAdmin.fieldsets + (("SMART SHRIMP", {"fields": ("role", "failed_login_attempts", "locked_until")}),)
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (("SMART SHRIMP", {"fields": ("role",)}),)


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
