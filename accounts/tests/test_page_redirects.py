"""回归测试：登录后跳回原页面的 next 参数不得被用于开放重定向。

这层防护此前没有任何测试覆盖，而它正是「登录页 + next 跳转」功能里唯一
对外的攻击面：一旦 _safe_next 放行了站外地址，任何人都能构造
`/?next=https://钓鱼站` 把刚登录成功的同学带走，而且因为登录是真实的，
受害者几乎无法察觉。
"""

from io import StringIO
from urllib.parse import parse_qs, urlparse

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory, TestCase

from accounts.authentication import _safe_next, login_required_page
from accounts.roles import STUDENT

User = get_user_model()
PASSWORD = "Bamboo!River-7429-Cloud"


class SafeNextTests(TestCase):
    """_safe_next 只放行站内相对路径。"""

    def test_accepts_site_relative_paths(self):
        for value in ("/teacher/", "/game/?x=1", "/"):
            with self.subTest(value=value):
                self.assertEqual(_safe_next(value), value)

    def test_rejects_targets_that_leave_the_site(self):
        for value in (
            "//evil.example",  # 协议相对：浏览器会当成站外主机
            "///evil.example",  # 三斜杠，同上
            "https://evil.example",  # 完整网址
            "http://evil.example/x",
            "javascript:alert(1)",  # 伪协议
            "evil.example",  # 缺少前导斜杠
            "/\\evil.example",  # 反斜杠被部分浏览器当作斜杠
            "/\\/evil.example",
            "/\t/evil.example",  # 控制字符
            "/\n/evil.example",
            "",
            None,
        ):
            with self.subTest(value=value):
                self.assertEqual(_safe_next(value), "")

    def test_rejects_values_that_are_not_text(self):
        for value in (123, 0, [], {}, object()):
            with self.subTest(value=value):
                self.assertEqual(_safe_next(value), "")


class LoginRequiredPageTests(TestCase):
    """login_required_page 对未登录/被停用的访问者一律送去登录页。"""

    @classmethod
    def setUpTestData(cls):
        call_command("init_roles", stdout=StringIO())
        cls.alice = User.objects.create_user("alice01", display_name="小明", password=PASSWORD)
        cls.alice.groups.add(Group.objects.get(name=STUDENT))

    def setUp(self):
        @login_required_page
        def view(request):
            return HttpResponse("protected-shell")

        self.view = view
        self.factory = RequestFactory()

    def redirect_target(self, response):
        self.assertEqual(response.status_code, 302)
        location = urlparse(response["Location"])
        self.assertTrue(location.path.startswith("/"), location.path)
        self.assertEqual(location.netloc, "")
        return parse_qs(location.query)

    def test_anonymous_visitor_is_sent_to_login_with_return_path(self):
        request = self.factory.get("/teacher/")
        request.user = AnonymousUser()
        self.assertEqual(self.redirect_target(self.view(request)), {"next": ["/teacher/"]})

    def test_return_path_keeps_the_query_string(self):
        request = self.factory.get("/teacher/students", {"page": "2"})
        request.user = AnonymousUser()
        self.assertEqual(
            self.redirect_target(self.view(request)),
            {"next": ["/teacher/students?page=2"]},
        )

    def test_deactivated_user_is_treated_as_anonymous(self):
        self.alice.is_active = False
        request = self.factory.get("/teacher/")
        request.user = self.alice
        self.redirect_target(self.view(request))

    def test_authenticated_user_reaches_the_view(self):
        request = self.factory.get("/teacher/")
        request.user = self.alice
        response = self.view(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"protected-shell")
