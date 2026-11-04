"""Vistas HTML de autenticación y perfil."""

from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .services import authenticate_user, record_event


@require_http_methods(["GET", "POST"])
def login_view(request):
    """Inicia sesión y registra intentos fallidos o exitosos."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    message = ""
    if request.method == "POST":
        user, error = authenticate_user(
            request.POST.get("username", "").strip(), request.POST.get("password", ""),
            request.META.get("REMOTE_ADDR"),
        )
        if user:
            login(request, user)
            return redirect("dashboard")
        message = "La cuenta está bloqueada temporalmente." if error == "account_locked" else "Usuario o contraseña incorrectos."
    return render(request, "accounts/login.html", {"error_message": message})


@login_required
def profile_view(request):
    """Muestra la identidad y el rol de la sesión actual."""
    return render(request, "accounts/profile.html")


@login_required
def logout_view(request):
    """Cierra la sesión activa y registra el evento."""
    record_event("logout.succeeded", request.user, ip_address=request.META.get("REMOTE_ADDR"))
    logout(request)
    return redirect("login")
