"""Serializadores de API para administración de cuentas."""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from apps.accounts.models import User


class UserSerializer(serializers.ModelSerializer):
    """Representa datos de usuario sin exponer credenciales.

    password_changed indica quién y cuándo cambió la contraseña por última vez (nunca la contraseña); se calcula
    una sola vez para toda la lista y llega en el contexto ("password_changes", ver services.password_changes).
    """

    password_changed = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "username", "first_name", "last_name", "email", "role", "is_active", "date_joined",
                  "password_changed")
        read_only_fields = ("id", "date_joined")

    def get_password_changed(self, user):
        change = self.context.get("password_changes", {}).get(user.pk)
        return {**change, "at": change["at"].isoformat()} if change else None


class UserCreateSerializer(serializers.Serializer):
    """Valida los campos requeridos al crear una cuenta."""

    username = serializers.CharField(max_length=150)
    password = serializers.CharField(write_only=True, trim_whitespace=False)
    role = serializers.ChoiceField(choices=User.Role.choices)
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)

    def validate_username(self, value):
        # Sin distinguir mayúsculas: el login tampoco las distingue ("Operario" chocaría con "operario").
        if User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("Ese nombre de usuario ya está registrado.")
        return value

    def validate(self, attrs):
        # Las reglas de AUTH_PASSWORD_VALIDATORS lanzan el ValidationError de Django, que DRF no traduce (daría un
        # 500 sin motivo). Se validan aquí, con los datos del usuario nuevo, para responder 400 con el mensaje.
        candidate = User(**{key: attrs.get(key, "") for key in ("username", "first_name", "last_name", "email")})
        try:
            validate_password(attrs["password"], candidate)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"password": list(error.messages)}) from error
        return attrs


class PasswordSetSerializer(serializers.Serializer):
    """Contraseña nueva que el administrador asigna a una cuenta; aplica AUTH_PASSWORD_VALIDATORS."""

    password = serializers.CharField(write_only=True, trim_whitespace=False)

    def validate_password(self, value):
        try:
            validate_password(value, self.context["user"])
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error
        return value


class UserUpdateSerializer(serializers.Serializer):
    """Valida cambios de rol o activación."""

    role = serializers.ChoiceField(choices=User.Role.choices, required=False)
    is_active = serializers.BooleanField(required=False)
