"""Restricted HTML maintenance: no general Django admin or privilege editor."""
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from functools import wraps
import logging

from classrooms.models import Classroom, StudentEnrollment, TeacherClassGrant
from .models import MaintenanceEvent
from .authentication import authenticated_user
from core.api import ApiError

User = get_user_model()


def safe_maintenance(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        try:
            return view(*args, **kwargs)
        except DatabaseError:
            logging.getLogger(__name__).error("Maintenance database failure; request data omitted.")
            return HttpResponse("维护服务暂不可用。结果未确认，请返回首页核对后重试。", status=503, headers={"Cache-Control": "no-store"})
    return wrapped


def allowed(user):
    if not user.is_authenticated or not user.is_active or not user.groups.filter(name="maintainer").exists():
        return False
    for app, model, code in [("accounts", "user", "maintain_accounts"), ("classrooms", "classroom", "maintain_class_assignments")]:
        if not Permission.objects.filter(content_type__app_label=app, content_type__model=model, codename=code).filter(Q(group__user=user) | Q(user=user)).exists():
            return False
    return True


def editable_users():
    return User.objects.filter(is_staff=False, is_superuser=False).exclude(groups__name="maintainer")


class ConfirmedForm(forms.Form):
    confirm = forms.BooleanField(label="我已核对目标、当前值和变更内容，确认执行")


class AccountForm(ConfirmedForm):
    user = forms.ModelChoiceField(label="账号", queryset=User.objects.none())
    version = forms.IntegerField(label="当前版本号", min_value=0)
    active = forms.BooleanField(label="启用账号", required=False)
    teacher = forms.BooleanField(label="授予教师身份", required=False)


class ClassForm(ConfirmedForm):
    code = forms.CharField(label="班级编号", max_length=32)
    name = forms.CharField(label="班级名称", max_length=80)


class ClassUpdateForm(ClassForm):
    classroom = forms.ModelChoiceField(label="班级", queryset=Classroom.objects.none())
    version = forms.IntegerField(label="当前版本号", min_value=0)
    active = forms.BooleanField(label="启用班级", required=False)


class EnrollmentForm(ConfirmedForm):
    user = forms.ModelChoiceField(label="在班玩家账号", queryset=User.objects.none())
    version = forms.IntegerField(label="账号当前版本号", min_value=0)
    classroom = forms.ModelChoiceField(label="学生班级（留空取消归属）", required=False, queryset=Classroom.objects.none())


class GrantForm(EnrollmentForm):
    classroom = forms.ModelChoiceField(label="授权班级", queryset=Classroom.objects.none())
    grant = forms.BooleanField(label="授予授权（取消勾选为撤销）", required=False)


FORM_TYPES = {"account": AccountForm, "create_class": ClassForm, "class": ClassUpdateForm, "enrollment": EnrollmentForm, "grant": GrantForm}
LABELS = {"account": "修改账号启用状态与教师身份", "create_class": "创建班级", "class": "修改班级", "enrollment": "调整学生归属", "grant": "调整教师班级授权"}


def build_form(action, data=None):
    form = FORM_TYPES[action](data)
    if "user" in form.fields:
        form.fields["user"].queryset = editable_users().order_by("username")
        form.fields["user"].label_from_instance = lambda user: f"{user.username} · {user.display_name}"
    if "classroom" in form.fields:
        form.fields["classroom"].queryset = Classroom.objects.order_by("code")
    form.order_fields([key for key in form.fields if key != "confirm"] + ["confirm"])
    if data is not None and (set(data) - set(form.fields) - {"csrfmiddlewaretoken"} or any(len(data.getlist(key)) != 1 for key in data)):
        form.add_error(None, "包含不支持的字段，未执行操作。")
    return form


def record(actor, action, target, before, after):
    MaintenanceEvent.objects.create(actor=actor, action=action, target=str(target), before=before, after=after)


def conflict():
    raise ValidationError("记录已变化，请返回维护首页核对最新版本号后重新操作。")


@transaction.atomic
def apply(actor_id, action, data):
    actor = User.objects.select_for_update().get(pk=actor_id)
    if not allowed(actor):
        raise ValidationError("维护权限已失效，请重新登录。")
    if action == "create_class":
        obj = Classroom(code=data["code"], name=data["name"])
        obj.full_clean()
        obj.save()
        record(actor, action, obj.pk, {}, {"code": obj.code, "name": obj.name, "active": True})
        return
    if action == "class":
        obj = Classroom.objects.select_for_update().get(pk=data["classroom"].pk)
        if obj.maintenance_version != data["version"]:
            conflict()
        before = {"code": obj.code, "name": obj.name, "active": obj.is_active}
        obj.code, obj.name, obj.is_active = data["code"], data["name"], data["active"]
        obj.maintenance_version += 1
        obj.full_clean()
        obj.save()
        record(actor, action, obj.pk, before, {"code": obj.code, "name": obj.name, "active": obj.is_active})
        return
    user = editable_users().select_for_update().filter(pk=data["user"].pk).first()
    if user is None or user.pk == actor.pk:
        raise ValidationError("不能通过此入口修改自己或特权账号。")
    if user.session_revision != data["version"]:
        conflict()
    if action == "account":
        old_grants = [str(pk) for pk in TeacherClassGrant.objects.filter(teacher=user).order_by("classroom_id").values_list("classroom_id", flat=True)]
        before = {"active": user.is_active, "teacher": user.groups.filter(name="teacher").exists(), "teachingClassIds": old_grants}
        user.is_active = data["active"]
        teacher_group = Group.objects.get(name="teacher")
        if data["teacher"]:
            user.groups.add(teacher_group)
        else:
            user.groups.remove(teacher_group)
            TeacherClassGrant.objects.filter(teacher=user).delete()
        after = {"active": user.is_active, "teacher": data["teacher"], "teachingClassIds": old_grants if data["teacher"] else []}
    else:
        classroom = data["classroom"]
        if classroom:
            classroom = Classroom.objects.select_for_update().get(pk=classroom.pk)
            if not classroom.is_active and (action == "enrollment" or data["grant"]):
                raise ValidationError("不能向停用班级分配学生或新增授权。")
        if action == "enrollment":
            before = {"classId": str(StudentEnrollment.objects.filter(student=user).values_list("classroom_id", flat=True).first() or "")}
            if classroom:
                if not user.is_active:
                    raise ValidationError("不能分配停用账号。")
                StudentEnrollment.objects.update_or_create(student=user, defaults={"classroom": classroom})
            else:
                StudentEnrollment.objects.filter(student=user).delete()
            after = {"classId": str(classroom.pk) if classroom else ""}
        else:
            if data["grant"] and (not user.is_active or not user.groups.filter(name="teacher").exists()):
                raise ValidationError("新增授权需要启用的教师账号。")
            before = {"classId": str(classroom.pk), "granted": TeacherClassGrant.objects.filter(teacher=user, classroom=classroom).exists()}
            if data["grant"]:
                TeacherClassGrant.objects.get_or_create(teacher=user, classroom=classroom)
            else:
                TeacherClassGrant.objects.filter(teacher=user, classroom=classroom).delete()
            after = {"classId": str(classroom.pk), "granted": data["grant"]}
    # A monotonic revision both prevents stale writes and permanently invalidates
    # all prior session auth hashes, including never-presented device tokens.
    user.session_revision += 1
    user.save(update_fields=["session_revision", "is_active"])
    before["username"] = user.username
    after["username"] = user.username
    record(actor, action, user.pk, before, after)


@never_cache
@safe_maintenance
@require_http_methods(["GET", "POST"])
def workspace(request, action=None):
    try:
        authenticated_user(request)
    except ApiError:
        return HttpResponse('登录已失效，请在<a href="/">账号中心重新登录</a>。', status=403)
    if not allowed(request.user):
        return HttpResponse('需要维护人员身份与权限。请先在<a href="/">账号中心登录</a>。', status=403)
    form = None
    if action:
        form = build_form(action, request.POST if request.method == "POST" else None)
        if request.method == "GET" and request.GET.get("user") and "user" in form.fields:
            try:
                target = editable_users().get(pk=request.GET["user"])
            except (User.DoesNotExist, ValidationError, ValueError):
                return HttpResponse("账号不存在或不可维护。", status=404)
            enrollment = StudentEnrollment.objects.filter(student=target).first()
            form.initial.update(user=target, version=target.session_revision, active=target.is_active,
                teacher=target.groups.filter(name="teacher").exists(), classroom=enrollment.classroom_id if enrollment and action == "enrollment" else None)
        if request.method == "GET" and action == "class" and request.GET.get("classroom"):
            try:
                target_class = Classroom.objects.get(pk=request.GET["classroom"])
            except (Classroom.DoesNotExist, ValidationError, ValueError):
                return HttpResponse("班级不存在。", status=404)
            form.initial.update(classroom=target_class, version=target_class.maintenance_version, code=target_class.code, name=target_class.name, active=target_class.is_active)
        if request.method == "POST" and form.is_valid():
            try:
                apply(request.user.pk, action, form.cleaned_data)
            except (ValidationError, IntegrityError) as error:
                form.add_error(None, error if isinstance(error, ValidationError) else "记录冲突，未保存，请核对后重试。")
            else:
                return redirect("/maintenance/?saved=1")
    elif request.method == "POST":
        return HttpResponse("请选择具体维护操作。", status=405)
    users = Paginator(editable_users().order_by("username").prefetch_related("groups", "class_grants__classroom").select_related("enrollment__classroom"), 30).get_page(request.GET.get("page"))
    for user in users:
        user.maintenance_teacher = any(group.name == "teacher" for group in user.groups.all())
        user.maintenance_grants = "、".join(grant.classroom.code for grant in user.class_grants.all()) or "无"
    events = list(MaintenanceEvent.objects.select_related("actor").order_by("-pk")[:50])
    for event in events:
        event.action_label = LABELS.get(event.action, "本机维护身份引导")
    return render(request, "maintenance.html", {"form": form, "action_label": LABELS.get(action), "users": users,
        "classes": Classroom.objects.order_by("code")[:100], "events": events,
        "operations": LABELS.items(), "saved": request.GET.get("saved") == "1"})
