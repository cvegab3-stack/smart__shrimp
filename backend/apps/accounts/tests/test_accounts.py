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
