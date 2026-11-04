"""Serializadores de API para administración de cuentas."""

from rest_framework import serializers

from apps.accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    """Representa datos de usuario sin exponer credenciales."""

    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "email", "role", "is_active", "date_joined")
        read_only_fields = ("id", "date_joined")


class UserCreateSerializer(serializers.Serializer):
    """Valida los campos requeridos al crear una cuenta."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    role = serializers.ChoiceField(choices=User.Role.choices)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Ese nombre de usuario ya está registrado.")
        return value


class UserUpdateSerializer(serializers.Serializer):
    """Valida cambios de rol o activación."""

    role = serializers.ChoiceField(choices=User.Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)
