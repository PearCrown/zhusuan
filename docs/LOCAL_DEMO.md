# 可选：在自己的本地数据库准备教师演示

第7组本地版本已有维护台，优先按 [MAINTENANCE.md](MAINTENANCE.md) 初始化维护人员并通过网页授权。下文保留此前第1—6组手动演示方式，直接shell操作不经过新增的维护审计和会话撤销服务，不应作为正式维护流程。

维护后台尚未实现。刚下载项目时，没有默认教师账号、共享密码或预置班级；页面注册也不能自选教师。以下是由拥有本机终端和数据库权限的开发人员执行的一次性演示准备，不是开放给普通用户的接口。

先按README启动本地项目，在网页自行注册一个专用于演示的账号，并记住用户名和密码。不要用真实师生资料。然后在项目目录运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 manage.py shell
```

在Python交互窗口逐行执行，先把下面的 `your_demo_username` 换成你刚注册的用户名：

```python
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from classrooms.models import Classroom, TeacherClassGrant

assert settings.DEBUG and settings.DATABASES['default']['HOST'] == '127.0.0.1'
teacher = get_user_model().objects.get(username='your_demo_username', is_active=True)
```

接着把下面整个with代码块粘贴进去，最后输入空行结束代码块：

```python
with transaction.atomic():
    classroom, _ = Classroom.objects.get_or_create(code='DEMO-A', defaults={'name': '本地演示班'})
    teacher.groups.add(Group.objects.get(name='teacher'))
    TeacherClassGrant.objects.get_or_create(teacher=teacher, classroom=classroom)
```

执行 `exit()` 退出。使用该账号登录或刷新身份，点击“查看授权班级”，即可看到本地演示班。没有学生归属记录时，名单为空，CSV只有表头，这是正常结果。此操作不设置staff或superuser，不获得管理后台权限，也不访问别人的数据库。

以后撤销这个演示账号的班级访问，可在同一个shell中找到相同的teacher和classroom，再执行：

```python
TeacherClassGrant.objects.filter(teacher=teacher, classroom=classroom).delete()
```

这只删除授权关系，保留账号和班级。下一次班级查询或名单导出会被拒绝；已有下载文件不会自动消失。正式维护授权、审计、学生归属变更及账号停用，应在后续第7组实现受控入口，不能把这些终端命令直接包装成无保护的网页功能。
