"""Rutas REST de cuentas."""

from django.urls import path

from .views import UserDetailView, UserListCreateView, UserPasswordView

urlpatterns = [
    path("users/", UserListCreateView.as_view(), name="user-list-create"),
    path("users/<int:pk>/", UserDetailView.as_view(), name="user-detail"),
    path("users/<int:pk>/password/", UserPasswordView.as_view(), name="user-password"),
]
