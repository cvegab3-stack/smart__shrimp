"""Vistas HTML de autenticación y perfil."""

from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .models import User
from .services import authenticate_user, change_own_password, record_event


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Inicia sesión solo por el perfil del rol de la cuenta y registra intentos fallidos o exitosos."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    message = ""
    role = request.GET.get("role")
    # Sin un perfil válido la plantilla muestra la selección de perfiles: no se autentica nada.
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
    return render(request, "accounts/login.html", {"error_message": message})


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
