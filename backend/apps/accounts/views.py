"""Vistas HTML de autenticación y perfil."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from .api.exceptions import SESSION_EXPIRED_MESSAGE
from .models import User
from .services import authenticate_user, change_own_password, record_event


# TEMPORAL (solo desarrollo): con DEV_LOGIN_ANY_ROLE = True, «admin» / «admin» entra en cualquier perfil con una
# cuenta de prueba de ese rol (dev_operador, dev_supervisor…). Se activa solo en config/settings/local.py y nunca
# con DEBUG apagado. Para volver al ingreso normal: poner DEV_LOGIN_ANY_ROLE = False (o borrar la línea).
DEV_LOGIN_CREDENTIALS = ("admin", "admin")


def _dev_login_requested(request) -> bool:
    enabled = getattr(settings, "DEV_LOGIN_ANY_ROLE", False) and settings.DEBUG
    credentials = (request.POST.get("username", "").strip(), request.POST.get("password", ""))
    return bool(enabled) and credentials == DEV_LOGIN_CREDENTIALS


def _dev_user(role: str) -> User:
    user, created = User.objects.get_or_create(username=f"dev_{role}", defaults={"role": role, "is_active": True})
    if created:
        user.set_unusable_password()  # solo se entra con el atajo; no tiene contraseña propia
        user.save(update_fields=("password",))
    return user


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Inicia sesión solo por el perfil del rol de la cuenta y registra intentos fallidos o exitosos."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    message = ""
    role = request.GET.get("role")
    # Sin un perfil válido la plantilla muestra la selección de perfiles: no se autentica nada.
    if request.method == "POST" and role in User.Role.values and _dev_login_requested(request):
        login(request, _dev_user(role), backend="django.contrib.auth.backends.ModelBackend")
        record_event("login.dev_shortcut", request.user, {"role": role}, request.META.get("REMOTE_ADDR"))
        return redirect("dashboard")
    if request.method == "POST" and role in User.Role.values:
        user, error = authenticate_user(
            request.POST.get("username", "").strip(), request.POST.get("password", ""),
            request.META.get("REMOTE_ADDR"), expected_role=role,
        )
        if user:
            login(request, user)
            return redirect("dashboard")
        message = {
            "account_locked": "La cuenta está bloqueada temporalmente.",
            "account_inactive": "La cuenta está inactiva. Comunícate con el administrador.",
        }.get(error, "Usuario, contraseña o perfil incorrectos.")
    # ?expired=1 lo añade session_timeout.js al vencer la sesión por inactividad.
    return render(request, "accounts/login.html", {"error_message": message,
                                                   "session_expired": request.GET.get("expired") == "1"})


@login_required
@require_http_methods(["GET", "POST"])
def profile_view(request):
    """Muestra la identidad y el rol de la sesión actual y permite cambiar la propia contraseña."""
    form = PasswordChangeForm(user=request.user, data=request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        # PasswordChangeForm ya comprobó la contraseña actual, la confirmación y AUTH_PASSWORD_VALIDATORS.
        change_own_password(request.user, form.cleaned_data["new_password1"], request.META.get("REMOTE_ADDR"))
        update_session_auth_hash(request, request.user)  # cambiar la contraseña no cierra esta sesión
        messages.success(request, "Contraseña actualizada.")
        return redirect("profile")
    return render(request, "accounts/profile.html", {"password_form": form})


@login_required
def logout_view(request):
    """Cierra la sesión activa y registra el evento."""
    record_event("logout.succeeded", request.user, ip_address=request.META.get("REMOTE_ADDR"))
    logout(request)
    return redirect("login")


@require_POST
def session_keepalive_view(request):
    """"Seguir conectado": la petición en sí renueva la sesión (SESSION_SAVE_EVERY_REQUEST). Sin sesión, 401."""
    if not request.user.is_authenticated:
        return JsonResponse({"detail": SESSION_EXPIRED_MESSAGE, "code": "session_expired"}, status=401)
    return JsonResponse({"expires_in": request.session.get_expiry_age()})
