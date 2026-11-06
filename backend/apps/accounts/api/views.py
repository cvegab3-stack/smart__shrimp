"""API administrativa de gestión de cuentas."""

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import AdministratorOnly
from apps.accounts.services import (AccountPolicyError, create_user, password_changes, set_user_password,
                                    update_user)

from .serializers import PasswordSetSerializer, UserCreateSerializer, UserSerializer, UserUpdateSerializer


class UserListCreateView(APIView):
    """Lista y crea usuarios; reservado al administrador."""

    permission_classes = (AdministratorOnly,)

    def get(self, request):
        users = User.objects.order_by("username")
        return Response(UserSerializer(users, many=True, context={"password_changes": password_changes()}).data)

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = create_user(**serializer.validated_data, actor=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    """Consulta o edita una cuenta (datos, rol y estado); reservado al administrador."""

    permission_classes = (AdministratorOnly,)

    def get_object(self, pk):
        return generics.get_object_or_404(User, pk=pk)

    def get(self, request, pk):
        return Response(UserSerializer(self.get_object(pk)).data)

    def patch(self, request, pk):
        user = self.get_object(pk)
        serializer = UserUpdateSerializer(data=request.data, context={"user": user})
        serializer.is_valid(raise_exception=True)
        try:
            user = update_user(user, **serializer.validated_data, actor=request.user,
                               ip_address=request.META.get("REMOTE_ADDR"))
        except AccountPolicyError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(UserSerializer(user, context={"password_changes": password_changes()}).data)


class UserPasswordView(APIView):
    """El administrador asigna una contraseña nueva a cualquier cuenta. No se devuelve ni se guarda en claro."""

    permission_classes = (AdministratorOnly,)

    def post(self, request, pk):
        user = generics.get_object_or_404(User, pk=pk)
        serializer = PasswordSetSerializer(data=request.data, context={"user": user})
        serializer.is_valid(raise_exception=True)
        set_user_password(user, serializer.validated_data["password"], actor=request.user,
                          ip_address=request.META.get("REMOTE_ADDR"))
        return Response(status=status.HTTP_204_NO_CONTENT)
