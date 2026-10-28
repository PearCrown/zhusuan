from datetime import timedelta
from io import StringIO
from django.test import TestCase
from django.core.management import call_command, CommandError
from django.utils import timezone
from accounts.models import User, VerifiedContact, ContactChallenge, MaintenanceEvent


class CleanupTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user("cleanup_owner",display_name="同学")
        VerifiedContact.objects.create(user=self.user,kind="email",value="owner@example.com",verified_at=timezone.now())
        MaintenanceEvent.objects.create(actor=self.user,action="test",target=str(self.user.pk),before={},after={})
        self.old=self.make(-3)
        self.consumed=self.make(-3,consumed_at=timezone.now()-timedelta(days=3))
        self.recent=self.make(-0.5)
        self.active=self.make(1)

    def make(self, days, **extra):
        return ContactChallenge.objects.create(user=self.user,purpose="login",kind="email",destination="owner@example.com",browser_digest="b"*64,code_digest="c"*64,auth_stamp="a"*64,expires_at=timezone.now()+timedelta(days=days),**extra)

    def run_command(self, **kwargs):
        out=StringIO();call_command("prune_contact_challenges",stdout=out,**kwargs);return out.getvalue()

    def test_preview_is_default_and_does_not_expose_addresses(self):
        text=self.run_command()
        self.assertIn("2条",text);self.assertNotIn("owner",text)
        self.assertEqual(ContactChallenge.objects.count(),4)

    def test_execute_removes_only_old_challenges_and_is_repeatable(self):
        self.run_command(execute=True)
        self.assertSetEqual(set(ContactChallenge.objects.values_list("pk",flat=True)),{self.recent.pk,self.active.pk})
        self.assertEqual(User.objects.count(),1);self.assertEqual(VerifiedContact.objects.count(),1);self.assertEqual(MaintenanceEvent.objects.count(),1)
        self.assertIn("0条",self.run_command(execute=True))

    def test_batch_limit_and_retention(self):
        self.run_command(execute=True,batch_size=1,max_batches=1)
        self.assertEqual(ContactChallenge.objects.count(),3)
        self.run_command(execute=True,retention_days=7)
        self.assertEqual(ContactChallenge.objects.count(),3)

    def test_invalid_options_never_delete(self):
        for options in [{"retention_days":0},{"batch_size":0},{"max_batches":1001}]:
            with self.assertRaises(CommandError):self.run_command(execute=True,**options)
        self.assertEqual(ContactChallenge.objects.count(),4)


from concurrent.futures import ThreadPoolExecutor
from django.test import TransactionTestCase
from django.db import connections, transaction


class CleanupConcurrencyTests(TransactionTestCase):
    setUp=CleanupTests.setUp
    make=CleanupTests.make
    run_command=CleanupTests.run_command

    def test_locked_challenge_is_skipped_and_available_on_next_run(self):
        def worker():
            try:
                return self.run_command(execute=True)
            finally:
                connections.close_all()
        with transaction.atomic():
            ContactChallenge.objects.select_for_update().get(pk=self.old.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                text=pool.submit(worker).result(timeout=10)
            self.assertIn("1条",text)
            self.assertTrue(ContactChallenge.objects.filter(pk=self.old.pk).exists())
        self.assertIn("1条",self.run_command(execute=True))
        self.assertEqual(VerifiedContact.objects.count(),1)
