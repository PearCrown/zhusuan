from django.test import SimpleTestCase


class AccountPageTests(SimpleTestCase):
    def test_page_is_public_has_no_identity_and_is_not_cached(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, 'id="guest" hidden')
        self.assertContains(response, 'id="identity" aria-label="当前账号" hidden')
        self.assertContains(response, '/static/js/accounts.js')
        self.assertContains(response, 'method="post" action="/"', count=2)

    def test_page_never_accepts_post_as_a_credential_submission(self):
        response = self.client.post("/", {"username": "never-create", "password": "never-use"})
        self.assertEqual(response.status_code, 405)
