"""API administrativa de gestión de cuentas."""

from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.accounts.permissions import AdministratorOnly
from apps.accounts.services import create_user, update_user

from .serializers import UserCreateSerializer, UserSerializer, UserUpdateSerializer


class UserListCreateView(APIView):
    """Lista y crea usuarios; reservado al administrador."""

    permission_classes = (AdministratorOnly,)

    def get(self, request):
        users = User.objects.order_by("username")
        return Response(UserSerializer(users, many=True).data)

    def post(self, request):
        serializer = UserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = create_user(**serializer.validated_data, actor=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)


class UserDetailView(APIView):
    """Consulta o modifica rol y estado; reservado al administrador."""

    permission_classes = (AdministratorOnly,)

    def get_object(self, pk):
        return generics.get_object_or_404(User, pk=pk)

    def get(self, request, pk):
        return Response(UserSerializer(self.get_object(pk)).data)

    def patch(self, request, pk):
        serializer = UserUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = update_user(self.get_object(pk), **serializer.validated_data, actor=request.user, ip_address=request.META.get("REMOTE_ADDR"))
        return Response(UserSerializer(user).data)
