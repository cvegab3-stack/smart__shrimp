"""Pruebas funcionales de autenticación y autorización de cuentas."""

from datetime import timedelta

from django.test import TestCase, override_settings
from django.test import Client
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import AuditEvent, User
from apps.accounts.services import authenticate_user, create_user


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class AccountServiceTests(TestCase):
    """Verifica hash, cierre de sesión y bloqueo temporal."""

    def setUp(self):
        self.user = User.objects.create_user(username="operator", password="A-strong-test-password", role=User.Role.OPERATOR)

    def test_password_is_hashed_and_success_is_audited(self):
        self.assertNotEqual(self.user.password, "A-strong-test-password")
        self.assertTrue(self.user.check_password("A-strong-test-password"))
        user, error = authenticate_user("operator", "A-strong-test-password", "127.0.0.1")
        self.assertEqual(user.pk, self.user.pk)
        self.assertIsNone(error)
        self.assertTrue(AuditEvent.objects.filter(action="login.succeeded").exists())

    def test_three_failed_attempts_lock_for_fifteen_minutes(self):
        for _ in range(3):
            authenticate_user("operator", "wrong-password")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 3)
        self.assertGreaterEqual(self.user.locked_until, timezone.now() + timedelta(minutes=14, seconds=59))
        self.assertEqual(authenticate_user("operator", "A-strong-test-password")[1], "account_locked")

    def test_expired_lock_allows_a_fresh_attempt(self):
        self.user.failed_login_attempts = 3
        self.user.locked_until = timezone.now() - timedelta(seconds=1)
        self.user.save(update_fields=("failed_login_attempts", "locked_until"))
        self.assertIsNone(authenticate_user("operator", "A-strong-test-password")[1])

    def test_audit_events_reject_mutation_and_deletion(self):
        event = AuditEvent.objects.create(action="sample", details={"safe": True})
        with self.assertRaises(TypeError):
            event.delete()
        with self.assertRaises(TypeError):
            AuditEvent.objects.filter(pk=event.pk).update(action="changed")
        with self.assertRaises(TypeError):
            AuditEvent.objects.filter(pk=event.pk).delete()

    def test_user_creation_service_uses_role_and_hash(self):
        user = create_user(username="quality", password="Distinct-Strong-Password-903!", role=User.Role.QUALITY)
        self.assertEqual(user.role, User.Role.QUALITY)
        self.assertTrue(user.check_password("Distinct-Strong-Password-903!"))

    def test_django_superuser_receives_administrator_role(self):
        user = User.objects.create_superuser("root", password="Distinct-Strong-Password-903!")
        self.assertEqual(user.role, User.Role.ADMINISTRATOR)


class AccountPermissionTests(TestCase):
    """Confirma 403 más bitácora para roles no autorizados."""

    def test_non_admin_cannot_manage_users_and_denial_is_audited(self):
        user = User.objects.create_user(username="operator", password="password", role=User.Role.OPERATOR)
        client = APIClient()
        client.force_authenticate(user)
        response = client.get("/api/accounts/users/")
        self.assertEqual(response.status_code, 403)
        event = AuditEvent.objects.get(action="permission.denied")
        self.assertEqual(event.actor_id, user.pk)

    def test_role_pages_render_only_for_authorized_users(self):
        operator = User.objects.create_user("operator", password="password", role=User.Role.OPERATOR)
        administrator = User.objects.create_user("admin", password="password", role=User.Role.ADMINISTRATOR)
        supervisor = User.objects.create_user("supervisor", password="password", role=User.Role.SUPERVISOR)
        client = Client()
        self.assertEqual(client.get("/accounts/login/").status_code, 200)
        client.force_login(operator)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/analysis/new/").status_code, 200)
        self.assertEqual(client.get("/history/").status_code, 200)
        self.assertEqual(client.get("/reports/").status_code, 403)
        client.force_login(administrator)
        self.assertEqual(client.get("/calibration/").status_code, 200)
        self.assertEqual(client.get("/users/").status_code, 200)
        client.force_login(supervisor)
        self.assertEqual(client.get("/reports/").status_code, 200)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class UserCreationValidationTests(TestCase):
    """Una contraseña rechazada debe responder 400 con el motivo, no un error 500."""

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="Admin-Strong-Password-71!", role=User.Role.ADMINISTRATOR)
        self.client = APIClient()
        self.client.force_authenticate(self.admin)

    def test_weak_password_returns_400_with_reason_and_creates_nothing(self):
        for weak in ("12345678", "password", "Cort0!"):  # numérica, común, menos de 8 caracteres
            response = self.client.post("/api/accounts/users/", {
                "username": "operario", "password": weak, "role": User.Role.QUALITY, "first_name": "Operario",
            }, format="json")
            self.assertEqual(response.status_code, 400, weak)
            self.assertIn("password", response.json())
            self.assertTrue(response.json()["password"])
        self.assertFalse(User.objects.filter(username="operario").exists())
        self.assertFalse(AuditEvent.objects.filter(action="user.created").exists())

    def test_strong_password_creates_user(self):
        response = self.client.post("/api/accounts/users/", {
            "username": "operario", "password": "Camaron-Lote-2026!", "role": User.Role.QUALITY,
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.get(username="operario").role, User.Role.QUALITY)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class LoginProfileTests(TestCase):
    """Cada cuenta solo entra por el perfil de su rol."""

    PASSWORD = "Quality-Strong-Password-52!"

    def setUp(self):
        self.user = User.objects.create_user("calidad", password=self.PASSWORD, role=User.Role.QUALITY)

    def login(self, role=None, password=None):
        url = "/accounts/login/" + (f"?role={role}" if role else "")
        return Client().post(url, {"username": "calidad", "password": password or self.PASSWORD})

    def test_matching_profile_logs_in(self):
        response = self.login(User.Role.QUALITY)
        self.assertRedirects(response, "/", fetch_redirect_response=False)

    def test_other_profile_is_rejected_with_generic_message_and_audited(self):
        for role in (User.Role.SUPERVISOR, User.Role.OPERATOR, User.Role.ADMINISTRATOR):
            response = self.login(role)
            self.assertEqual(response.status_code, 200, role)
            self.assertNotIn("_auth_user_id", response.wsgi_request.session)
            self.assertContains(response, "Usuario, contraseña o perfil incorrectos.")
        self.assertEqual(AuditEvent.objects.filter(action="login.role_mismatch").count(), 2)
        self.assertTrue(AuditEvent.objects.filter(action="login.account_locked").exists())

    def test_profile_mismatch_counts_as_failed_attempt(self):
        user, error = authenticate_user("calidad", self.PASSWORD, expected_role=User.Role.SUPERVISOR)
        self.assertIsNone(user)
        self.assertEqual(error, "invalid_credentials")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)
        event = AuditEvent.objects.get(action="login.role_mismatch")
        self.assertEqual(event.details, {"expected_role": "supervisor"})

    def test_post_without_profile_does_not_log_in(self):
        response = self.login(None)
        self.assertNotIn("_auth_user_id", response.wsgi_request.session)
        self.assertFalse(AuditEvent.objects.filter(action="login.succeeded").exists())

    def test_every_password_field_page_loads_visibility_toggle(self):
        # password_toggle.js (cargado en base.html) añade el ojo a cada <input type="password"> de la página.
        admin = User.objects.create_user("admin", password="Admin-Strong-Password-71!", role=User.Role.ADMINISTRATOR)
        client = Client()
        pages = [client.get("/accounts/login/?role=operador")]
        client.force_login(admin)
        pages.append(client.get("/users/"))
        for response in pages:
            self.assertContains(response, 'type="password"')
            self.assertContains(response, "js/password_toggle.js")


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class PasswordChangeTests(TestCase):
    """El usuario cambia su contraseña en Mi perfil; el administrador cambia la de cualquiera y ve quién y cuándo."""

    OLD = "Operador-Clave-Inicial-31!"
    NEW = "Operador-Clave-Nueva-48!"

    def setUp(self):
        self.admin = User.objects.create_user("admin", password="Admin-Strong-Password-71!", role=User.Role.ADMINISTRATOR)
        self.user = User.objects.create_user("operario", password=self.OLD, role=User.Role.OPERATOR)

    def change_own(self, old, new1, new2=None):
        client = Client()
        client.force_login(self.user)
        return client, client.post("/accounts/profile/", {
            "old_password": old, "new_password1": new1, "new_password2": new2 or new1})

    def test_user_changes_own_password_keeps_session_and_is_audited(self):
        client, response = self.change_own(self.OLD, self.NEW)
        self.assertRedirects(response, "/accounts/profile/", fetch_redirect_response=False)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))
        self.assertEqual(client.get("/accounts/profile/").status_code, 200)  # sigue con la sesión abierta
        event = AuditEvent.objects.get(action="password.changed_by_user")
        self.assertEqual((event.actor_id, event.details), (self.user.pk, {"user_id": self.user.pk}))
        self.assertNotIn(self.NEW, str(event.details))

    def test_wrong_current_mismatch_or_weak_password_is_rejected(self):
        for old, new1, new2 in ((self.OLD + "x", self.NEW, None), (self.OLD, self.NEW, self.NEW + "x"),
                                (self.OLD, "12345678", None)):
            _, response = self.change_own(old, new1, new2)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "field-error")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.OLD))
        self.assertFalse(AuditEvent.objects.filter(action="password.changed_by_user").exists())

    def test_admin_sets_password_of_any_account_and_unlocks_it(self):
        self.user.failed_login_attempts = 3
        self.user.locked_until = timezone.now() + timedelta(minutes=10)
        self.user.save()
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post(f"/api/accounts/users/{self.user.pk}/password/", {"password": self.NEW}, format="json")
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")  # la contraseña no se devuelve
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.NEW))
        self.assertEqual((self.user.failed_login_attempts, self.user.locked_until), (0, None))
        event = AuditEvent.objects.get(action="password.reset_by_admin")
        self.assertEqual((event.actor_id, event.details), (self.admin.pk, {"user_id": self.user.pk}))

    def test_admin_weak_password_returns_400_and_non_admin_gets_403(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        response = client.post(f"/api/accounts/users/{self.user.pk}/password/", {"password": "12345678"}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("password", response.json())
        client.force_authenticate(self.user)
        response = client.post(f"/api/accounts/users/{self.admin.pk}/password/", {"password": self.NEW}, format="json")
        self.assertEqual(response.status_code, 403)
        self.admin.refresh_from_db()
        self.assertFalse(self.admin.check_password(self.NEW))

    def test_user_list_shows_who_and_when_but_never_the_password(self):
        client = APIClient()
        client.force_authenticate(self.admin)
        rows = {u["username"]: u for u in client.get("/api/accounts/users/").json()}
        self.assertIsNone(rows["operario"]["password_changed"])
        self.change_own(self.OLD, self.NEW)
        rows = {u["username"]: u for u in client.get("/api/accounts/users/").json()}
        self.assertEqual(rows["operario"]["password_changed"]["by"], "usuario")
        client.post(f"/api/accounts/users/{self.user.pk}/password/", {"password": "Asignada-Por-Admin-77!"}, format="json")
        listing = client.get("/api/accounts/users/")
        change = {u["username"]: u for u in listing.json()}["operario"]["password_changed"]
        self.assertEqual((change["by"], change["actor"]), ("administrador", "admin"))
        self.assertNotIn("Asignada-Por-Admin-77!", listing.content.decode())
        self.assertNotIn("pbkdf2", listing.content.decode())
        self.assertNotIn('"password"', listing.content.decode())


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class InactiveAccountLoginTests(TestCase):
    """Una cuenta inactiva con la contraseña correcta ve "cuenta inactiva"; con una incorrecta, el error genérico."""

    PASSWORD = "Supervisor-Strong-Password-64!"

    def setUp(self):
        self.user = User.objects.create_user("inspector", password=self.PASSWORD, role=User.Role.SUPERVISOR,
                                             is_active=False)

    def login(self, password, role=User.Role.SUPERVISOR):
        return Client().post(f"/accounts/login/?role={role}", {"username": "inspector", "password": password})

    def test_correct_credentials_show_inactive_without_counting_a_failure(self):
        for _ in range(4):  # más de 3: no debe bloquear, porque la contraseña es correcta
            response = self.login(self.PASSWORD)
            self.assertContains(response, "La cuenta está inactiva. Comunícate con el administrador.")
            self.assertNotIn("_auth_user_id", response.wsgi_request.session)
        self.user.refresh_from_db()
        self.assertEqual((self.user.failed_login_attempts, self.user.locked_until), (0, None))
        self.assertEqual(AuditEvent.objects.filter(action="login.inactive").count(), 4)

    def test_wrong_password_on_inactive_account_gets_generic_message(self):
        response = self.login("otra-clave-incorrecta")
        self.assertContains(response, "Usuario, contraseña o perfil incorrectos.")
        self.assertNotContains(response, "inactiva.")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)

    def test_inactive_wins_over_wrong_profile_and_reactivation_allows_login(self):
        self.assertContains(self.login(self.PASSWORD, User.Role.OPERATOR), "La cuenta está inactiva.")
        self.user.is_active = True
        self.user.save()
        self.assertRedirects(self.login(self.PASSWORD), "/", fetch_redirect_response=False)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class UsernameCaseTests(TestCase):
    """El usuario no distingue mayúsculas: "inspector" es la cuenta "Inspector"."""

    PASSWORD = "Supervisor-Strong-Password-64!"

    def setUp(self):
        self.user = User.objects.create_user("Inspector", password=self.PASSWORD, role=User.Role.SUPERVISOR)

    def login(self, username):
        return Client().post("/accounts/login/?role=supervisor", {"username": username, "password": self.PASSWORD})

    def test_inactive_account_typed_in_lowercase_shows_inactive(self):
        self.user.is_active = False
        self.user.save()
        response = self.login("inspector")
        self.assertContains(response, "La cuenta está inactiva. Comunícate con el administrador.")
        self.assertTrue(AuditEvent.objects.filter(action="login.inactive", actor_id=self.user.pk).exists())

    def test_active_account_logs_in_with_any_case(self):
        for username in ("inspector", "INSPECTOR", "Inspector"):
            self.assertRedirects(self.login(username), "/", fetch_redirect_response=False)

    def test_wrong_password_in_lowercase_counts_against_the_real_account(self):
        authenticate_user("inspector", "clave-incorrecta")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)

    def test_cannot_create_username_that_differs_only_in_case(self):
        admin = User.objects.create_user("admin", password="Admin-Strong-Password-71!", role=User.Role.ADMINISTRATOR)
        client = APIClient()
        client.force_authenticate(admin)
        response = client.post("/api/accounts/users/", {
            "username": "INSPECTOR", "password": "Otra-Clave-Segura-58!", "role": User.Role.OPERATOR}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("username", response.json())

    def test_legacy_accounts_differing_only_in_case_require_exact_match(self):
        twin = User.objects.create_user("inspector", password="Twin-Strong-Password-27!", role=User.Role.OPERATOR)
        self.assertEqual(authenticate_user("Inspector", self.PASSWORD)[0], self.user)
        self.assertEqual(authenticate_user("inspector", "Twin-Strong-Password-27!")[0], twin)
        self.assertEqual(authenticate_user("INSPECTOR", self.PASSWORD), (None, "invalid_credentials"))
