from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.db import IntegrityError, transaction
from django.test import TestCase, SimpleTestCase, override_settings
from django.utils import timezone
from accounts.models import User, VerifiedContact
from accounts.contacts import normalize_contact
from accounts.messaging import CodeMessage, get_sender, DeliveryUnavailable


class ContactTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("contact_owner", display_name="同学")
        self.other = User.objects.create_user("contact_other", display_name="另一同学")

    def bind(self, user, kind="email", value="Person@Example.com"):
        return VerifiedContact.objects.create(user=user, kind=kind, value=value, verified_at=timezone.now())

    def test_canonical_contact_and_user_are_separate_from_unverified_email(self):
        item = self.bind(self.user)
        self.assertEqual(item.value, "person@example.com")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")
        self.assertNotIn(item.value, str(item))
        self.assertEqual(item.user_id, self.user.pk)

    def test_global_identity_unique_and_one_per_kind_per_account(self):
        self.bind(self.user)
        for user, value in [(self.other, "PERSON@example.COM"), (self.user, "other@example.com")]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.bind(user, value=value)
        self.bind(self.user, "phone", "+8613812345678")
        self.assertEqual(VerifiedContact.objects.count(), 2)

    def test_invalid_and_unverified_records_are_rejected(self):
        for kind, value in [("email", "bad"), ("phone", "13812345678"), ("fax", "anything"), ("email", "a@example.com\nBcc:evil@example.com")]:
            with self.assertRaises(ValidationError): self.bind(self.user, kind, value)
        with self.assertRaises(ValidationError):
            VerifiedContact.objects.create(user=self.user, kind="email", value="a@example.com")
        self.assertEqual(VerifiedContact.objects.count(), 0)

    def test_database_rejects_noncanonical_bulk_bypass(self):
        for kind, value in [("email", "UPPER@example.com"), ("phone", "13812345678"), ("fax", "x")]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                VerifiedContact.objects.bulk_create([VerifiedContact(user=self.user, kind=kind, value=value, verified_at=timezone.now())])


class MessageTests(SimpleTestCase):
    def test_normalization_has_no_provider_specific_merging(self):
        self.assertEqual(normalize_contact("email", " A.B+tag@Example.com "), "a.b+tag@example.com")
        self.assertEqual(normalize_contact("phone", "+8613812345678"), "+8613812345678")
        for kind, value in [("phone", True), ("email", "测试@example.com"), ("phone", "+00123456789"), ("email", "a@b.com\nx")]:
            with self.assertRaises(ValidationError): normalize_contact(kind, value)

    @override_settings(CONTACT_MESSAGE_BACKEND="disabled")
    def test_disabled_is_fail_closed(self):
        with self.assertRaises(DeliveryUnavailable) as error:
            get_sender().send(CodeMessage("email", "private@example.com", "login", "123456"))
        self.assertNotIn("private", str(error.exception))
        self.assertNotIn("123456", str(error.exception))

    @override_settings(DEBUG=True, CONTACT_MESSAGE_BACKEND="memory")
    def test_memory_is_bounded_drainable_and_not_logged(self):
        sender = get_sender()
        self.addCleanup(sender.clear)
        message = CodeMessage("email", "Private@Example.com", "bind", "123456")
        self.assertNotIn("123456", repr(message))
        self.assertNotIn("private", repr(message))
        for _ in range(102): sender.send(message)
        self.assertEqual(len(sender.drain()), 100)
        self.assertEqual(sender.drain(), ())
        sender.send(message)
        with override_settings(DEBUG=False):
            with self.assertRaises(ImproperlyConfigured): sender.send(message)
        self.assertEqual(sender.drain(), ())

    def test_production_or_unknown_sender_is_rejected(self):
        for backend in ["memory", "arbitrary.module"]:
            with override_settings(DEBUG=False, CONTACT_MESSAGE_BACKEND=backend):
                with self.assertRaises(ImproperlyConfigured): get_sender()

    def test_codes_and_purposes_are_strict(self):
        for code in [123456, "１２３４５６", "12345", "123456\n"]:
            with self.assertRaises(ValidationError): CodeMessage("email", "a@example.com", "bind", code)
        with self.assertRaises(ValidationError): CodeMessage("email", "a@example.com", "unknown", "123456")
