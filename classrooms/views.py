import csv
from io import StringIO

from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from accounts.authentication import login_required_api
from core.api import ApiError, api_methods, success
from .access import EXPORT_ROSTER, authorized_class, teacher_classes
from .models import StudentEnrollment

PAGE_SIZE = 50
MAX_EXPORT_STUDENTS = 2000


def page_number(request, *, allow_page=True):
    allowed = {"page"} if allow_page else set()
    if set(request.GET) - allowed or any(len(request.GET.getlist(key)) != 1 for key in request.GET):
        raise ApiError("invalid_query", "查询参数无效。")
    value = request.GET.get("page", "1")
    if not value.isascii() or not value.isdecimal() or not 1 <= len(value) <= 6 or not 1 <= int(value) <= 100000:
        raise ApiError("invalid_query", "页码必须为1至100000的整数。")
    return int(value)


def class_data(classroom):
    return {"classId": str(classroom.pk), "code": classroom.code, "name": classroom.name}


def student_data(enrollment):
    return {"userId": str(enrollment.student_id), "username": enrollment.student.username, "displayName": enrollment.student.display_name}


def students_in(classroom):
    # Enrollment defines participation; a teacher can also be a learner.
    return StudentEnrollment.objects.filter(classroom_id=classroom.pk, student__is_active=True).select_related("student").order_by("student_id")


def paginate(query, page, serialize):
    total = query.count()
    offset = (page - 1) * PAGE_SIZE
    return {"items": [serialize(item) for item in query[offset:offset + PAGE_SIZE]], "page": page, "pageSize": PAGE_SIZE, "total": total, "hasNext": offset + PAGE_SIZE < total}


@require_safe
@never_cache
def workspace(request):
    # Public shell only; data is fetched from independently protected APIs.
    return render(request, "teacher.html")


@login_required_api
@api_methods("GET", "HEAD")
def classes(request):
    query = teacher_classes(request.account_user).order_by("code", "pk")
    return success(paginate(query, page_number(request), class_data))


@login_required_api
@api_methods("GET", "HEAD")
def students(request, class_id):
    classroom = authorized_class(request.account_user, class_id)
    page = page_number(request)
    return success({"classroom": class_data(classroom), **paginate(students_in(classroom), page, student_data)})


def csv_cell(value):
    # CSV quoting alone does not prevent spreadsheet formula execution.
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text


@login_required_api
@api_methods("GET", "HEAD")
def roster_csv(request, class_id):
    classroom = authorized_class(request.account_user, class_id, action=EXPORT_ROSTER)
    page_number(request, allow_page=False)
    rows = list(students_in(classroom)[:MAX_EXPORT_STUDENTS + 1])
    if len(rows) > MAX_EXPORT_STUDENTS:
        raise ApiError("export_too_large", "名单超过单次2000人导出上限，请联系维护人员。", 413)
    # Buffer before responding: DB/read failure must not produce a partial file.
    output = StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["用户编号", "用户名", "显示名称"])
    for row in rows:
        writer.writerow([str(row.student_id), csv_cell(row.student.username), csv_cell(row.student.display_name)])
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="class-{classroom.pk}-students.csv"'
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response
