from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.utils import timezone
from django.db import DatabaseError
from django.contrib.auth.models import Group
from core.api import ApiError
from accounts.models import User, VerifiedContact, ContactChallenge, RateLimitBucket
from accounts.messaging import get_sender, DeliveryUnavailable


@override_settings(DEBUG=True, CONTACT_MESSAGE_BACKEND="memory", PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CodeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("code_owner", display_name="同学", password="River!Cloud-7268")
        self.client = Client(enforce_csrf_checks=True)
        get_sender().clear()
        self.addCleanup(get_sender().clear)

    def post(self, purpose, stage, payload, client=None):
        c = client or self.client
        token = c.get("/auth/csrf").json()["data"]["csrfToken"]
        return c.post(f"/auth/code/{purpose}/{stage}", payload, content_type="application/json", HTTP_X_CSRFTOKEN=token)

    def contact(self):
        VerifiedContact.objects.create(user=self.user, kind="email", value="owner@example.com", verified_at=timezone.now())

    def issue(self, purpose="login"):
        response = self.post(purpose, "request", {"kind":"email", "destination":"owner@example.com", **({"currentPassword":"River!Cloud-7268"} if purpose=="bind" else {})})
        self.assertEqual(response.status_code, 202, response.content)
        message = get_sender().drain()[0]
        self.assertNotIn(message.code, response.content.decode())
        return {"challengeId": response.json()["data"]["challengeId"], "code": message.code}

    def test_bind_reauth_then_login_same_user_no_new_account(self):
        self.client.force_login(self.user)
        old = Client(); old.force_login(self.user)
        payload = self.issue("bind")
        self.assertEqual(self.post("bind","verify",payload).status_code,200)
        self.assertEqual(VerifiedContact.objects.get().user_id,self.user.pk)
        self.assertEqual(old.get("/auth/me").status_code,401)
        self.assertEqual(self.client.get("/auth/me").status_code,401)
        RateLimitBucket.objects.all().delete()
        login = self.issue()
        result = self.post("login","verify",login)
        self.assertEqual(result.status_code,200,result.content)
        self.assertEqual(result.json()["data"]["user"]["userId"],str(self.user.pk))
        self.assertEqual(self.post("login","verify",login).status_code,400)
        self.assertEqual(User.objects.count(),1)

    def test_unknown_address_is_generic_and_never_creates_account(self):
        response=self.post("login","request",{"kind":"email","destination":"missing@example.com"})
        self.assertEqual(response.status_code,202)
        self.assertEqual(get_sender().drain(),())
        self.assertEqual(self.post("login","verify",{"challengeId":response.json()["data"]["challengeId"],"code":"123456"}).status_code,400)
        self.assertEqual(User.objects.count(),1)

    def test_wrong_attempts_commit_and_fifth_locks_correct_code(self):
        self.contact(); payload=self.issue()
        wrong={**payload,"code":"000000" if payload["code"]!="000000" else "111111"}
        for _ in range(5):self.assertEqual(self.post("login","verify",wrong).status_code,400)
        self.assertEqual(ContactChallenge.objects.get().attempts,5)
        self.assertEqual(self.post("login","verify",payload).status_code,400)

    def test_purpose_and_browser_are_isolated(self):
        self.contact(); payload=self.issue()
        self.assertEqual(self.post("reset","verify",{**payload,"newPassword":"Different!Cloud-7281"}).status_code,400)
        self.assertEqual(self.post("login","verify",payload,client=Client(enforce_csrf_checks=True)).status_code,400)
        self.assertEqual(self.post("login","verify",payload).status_code,200)

    def test_expiry_and_password_changes_invalidate(self):
        self.contact(); payload=self.issue()
        ContactChallenge.objects.update(expires_at=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.post("login","verify",payload).status_code,400)
        ContactChallenge.objects.update(expires_at=timezone.now()+timedelta(minutes=5))
        self.user.set_password("Different!Cloud-7281");self.user.save()
        self.assertEqual(self.post("login","verify",payload).status_code,400)

    def test_reset_revokes_old_sessions_and_consumes_once(self):
        self.contact(); old=Client();old.force_login(self.user)
        payload={**self.issue("reset"),"newPassword":"Different!Cloud-7281"}
        self.assertEqual(self.post("reset","verify",payload).status_code,200)
        self.assertEqual(old.get("/auth/me").status_code,401)
        self.user.refresh_from_db();self.assertTrue(self.user.check_password(payload["newPassword"]))
        self.assertEqual(self.post("reset","verify",payload).status_code,400)

    def test_weak_reset_keeps_ticket_available_without_changing_password(self):
        self.contact(); payload=self.issue("reset")
        self.assertEqual(self.post("reset","verify",{**payload,"newPassword":"123"}).status_code,400)
        self.assertIsNone(ContactChallenge.objects.get().consumed_at)
        self.assertEqual(self.post("reset","verify",{**payload,"newPassword":"Different!Cloud-7281"}).status_code,200)

    def test_disabled_service_is_uniform_and_has_no_challenge(self):
        with override_settings(CONTACT_MESSAGE_BACKEND="disabled"):
            self.assertEqual(self.post("login","request",{"kind":"email","destination":"owner@example.com"}).status_code,503)
        self.assertFalse(ContactChallenge.objects.exists())

    def test_send_failure_rolls_back_and_secrets_are_not_stored(self):
        self.contact()
        with patch("accounts.messaging.MemorySender.send",side_effect=DeliveryUnavailable()):
            self.assertEqual(self.post("login","request",{"kind":"email","destination":"owner@example.com"}).status_code,503)
        self.assertFalse(ContactChallenge.objects.exists())
        RateLimitBucket.objects.all().delete();payload=self.issue()
        self.assertNotIn(payload["code"],ContactChallenge.objects.get().code_digest)

    def test_audit_failure_rolls_back_reset_and_consumption(self):
        self.contact();payload={**self.issue("reset"),"newPassword":"Different!Cloud-7281"}
        with patch("accounts.code_flows.password_audit",side_effect=DatabaseError("hidden")):
            response=self.post("reset","verify",payload)
        self.assertEqual(response.status_code,503)
        self.assertNotIn("hidden",response.content.decode())
        self.assertIsNone(ContactChallenge.objects.get().consumed_at)
        self.user.refresh_from_db();self.assertTrue(self.user.check_password("River!Cloud-7268"))

    def test_reissue_invalidates_prior_challenge_and_cooldown_blocks(self):
        self.contact(); old=self.issue()
        self.assertEqual(self.post("login","request",{"kind":"email","destination":"owner@example.com"}).status_code,429)
        RateLimitBucket.objects.all().delete();new=self.issue()
        self.assertEqual(self.post("login","verify",old).status_code,400)
        self.assertEqual(self.post("login","verify",new).status_code,200)

    def test_csrf_methods_fields_and_invalid_types(self):
        url="/auth/code/login/request"
        self.assertEqual(self.client.get(url).status_code,405)
        self.assertEqual(self.client.post(url,{},content_type="application/json").status_code,403)
        for body in [{"kind":"email","destination":"a@example.com","userId":str(self.user.pk)}, {"kind":[],"destination":True}]:
            self.assertEqual(self.post("login","request",body).status_code,400)
        self.assertEqual(self.post("login","verify",{"challengeId":[],"code":True}).status_code,400)

    def test_privileged_accounts_and_removed_contact_cannot_use_code(self):
        self.contact();payload=self.issue()
        self.user.is_staff=True;self.user.save()
        self.assertEqual(self.post("login","verify",payload).status_code,400)
        self.user.is_staff=False;self.user.save();VerifiedContact.objects.all().delete()
        self.assertEqual(self.post("login","verify",payload).status_code,400)

    def test_bind_does_not_overwrite_existing_or_take_another_identity(self):
        self.contact(); self.client.force_login(self.user)
        response=self.post("bind","request",{"kind":"email","destination":"new@example.com","currentPassword":"River!Cloud-7268"})
        self.assertEqual(response.status_code,409)
        self.assertEqual(VerifiedContact.objects.get().value,"owner@example.com")

    def test_bind_reauthentication_is_limited_across_destination_changes(self):
        self.client.force_login(self.user)
        for index in range(11):
            response=self.post("bind","request",{"kind":"email","destination":f"target{index}@example.com","currentPassword":"incorrect"})
            self.assertEqual(response.status_code,400 if index<10 else 429)
        self.assertFalse(ContactChallenge.objects.exists())

    def test_bind_identity_collision_and_failed_audit_are_atomic(self):
        self.client.force_login(self.user)
        payload=self.issue("bind")
        other=User.objects.create_user("other_owner",display_name="他人")
        VerifiedContact.objects.create(user=other,kind="email",value="owner@example.com",verified_at=timezone.now())
        self.assertEqual(self.post("bind","verify",payload).status_code,409)
        self.assertEqual(VerifiedContact.objects.get().user_id,other.pk)
        self.assertIsNone(ContactChallenge.objects.get().consumed_at)
        VerifiedContact.objects.all().delete()
        with patch("accounts.code_flows.MaintenanceEvent.objects.create",side_effect=DatabaseError("hidden")):
            self.assertEqual(self.post("bind","verify",payload).status_code,503)
        self.assertFalse(VerifiedContact.objects.exists())
        self.user.refresh_from_db();self.assertEqual(self.user.session_revision,0)


from concurrent.futures import ThreadPoolExecutor
from django.db import connections
from django.test import TransactionTestCase


@override_settings(DEBUG=True, CONTACT_MESSAGE_BACKEND="memory", PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CodeConcurrencyTests(TransactionTestCase):
    setUp=CodeTests.setUp
    post=CodeTests.post
    issue=CodeTests.issue
    contact=CodeTests.contact

    def test_two_reset_requests_consume_once(self):
        self.contact();payload={**self.issue("reset"),"newPassword":"Different!Cloud-7281"}
        cookies=self.client.cookies.copy()
        def worker(_):
            try:
                c=Client(enforce_csrf_checks=True);c.cookies=cookies.copy()
                return self.post("reset","verify",payload,client=c).status_code
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(worker,range(2))),[200,400])
        self.assertEqual(ContactChallenge.objects.exclude(consumed_at=None).count(),1)
