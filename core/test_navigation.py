from django.test import SimpleTestCase, override_settings
from django.template.loader import render_to_string
from django import forms


class NavigationTests(SimpleTestCase):
    @override_settings(CONTACT_MESSAGE_BACKEND="disabled")
    def test_home_omits_unavailable_verification_and_guest_game_shortcuts(self):
        response=self.client.get("/")
        self.assertNotContains(response,'href="/verification/"')
        self.assertContains(response,'href="/password/reset/"')
        self.assertEqual(response.content.decode().count('href="/game/"'),1)

    @override_settings(CONTACT_MESSAGE_BACKEND="memory")
    def test_available_verification_stays_in_account_sections(self):
        response=self.client.get("/")
        self.assertContains(response,'验证码登录或找回')
        self.assertContains(response,'验证联系方式')
        header=response.content.decode().split('</header>')[0]
        self.assertNotIn('/verification/',header)

    def test_maintenance_form_has_return_but_no_dashboard_navigation(self):
        class Form(forms.Form):
            name=forms.CharField()
        html=render_to_string('maintenance.html',{'form':Form(),'operations':[('password_reset','协助重置密码')]})
        self.assertIn('返回维护首页',html)
        self.assertIn('maintenance-form',html)
        self.assertNotIn('可维护账号（',html)
        self.assertNotIn('manual-reset-link',html)
        self.assertNotIn('<nav',html)

    def test_dashboard_retains_operations_without_self_link(self):
        html=render_to_string('maintenance.html',{'operations':[('password_reset','协助重置密码')],'users':[]})
        self.assertIn('href="/maintenance/password_reset/"',html)
        self.assertIn('可维护账号（',html)
        self.assertNotIn('返回维护首页',html)
        self.assertNotIn('manual-reset-link',html)

    def test_game_and_teacher_have_one_relevant_return_destination(self):
        self.assertNotIn('href="/teacher/"',render_to_string('game.html'))
        self.assertEqual(render_to_string('teacher.html').count('href="/"'),1)
