# 教师与班级访问控制（第6组）

账号中心在服务器分配teacher角色后显示“查看授权班级”，进入 `/teacher/`。该页面只是一层无数据的公开页面框架，实际列表、名单和CSV均由独立受保护接口读取。学生直接打开此网址也不会得到班级数据。

目前可以查看授权班级、启用账号名单及导出名单，不能查看游戏成绩或修改授权。教师身份、班级与学生归属的网页维护属于第7组；没有隐藏的默认管理员账号。

## 访问条件

每个请求依次检查：有效会话和启用账号、teacher组、所需操作权限、明确的TeacherClassGrant及启用班级。没有授权返回空列表；具体班级未授权、停用、不存在或编号无效统一404。不允许凭客户端role/userId或账号中心展示过的班级列表推断授权。

维护人员、staff或superuser标志本身不会绕过教师业务检查。应急管理员如确需教师业务访问，也必须另行具备teacher组、操作权限和具体班级授权。教师不需要student组才能游玩，归属名单也不按student组过滤。

| 请求 | 权限 | 返回 |
| --- | --- | --- |
| GET /teacher/api/classes?page=1 | view_class_progress | 仅当前授权且启用的班级 |
| GET /teacher/api/classes/{classId}/students?page=1 | view_class_progress + 本班授权 | 当前归属本班且启用的账号 |
| GET /teacher/api/classes/{classId}/students.csv | view_class_progress + export_class_roster + 本班授权 | 本班启用账号名单CSV |

都支持HEAD；其他方法在表单解析/CSRF之前拒绝405。不会通过GET改变账号、班级或授权。查询参数只允许单个page，CSV不接受查询参数；未知参数返回400。接口默认同站Cookie访问，无需关闭CSRF或引入浏览器持久令牌。

JSON沿用 `{ok:true,data:{...}}`；班级列表data包含items、page、pageSize、total、hasNext。items仅含classId/code/name。名单额外包含classroom对象，items仅含userId/username/displayName，不含密码摘要、邮箱、手机号、会话或其他班级信息。

每页50条，页码范围1—100000；超过实际末页返回空items。采用稳定字段顺序的偏移分页，并非冻结快照；翻页期间转班可能使计数和各页有所变化。以后需要成绩历史归属或大型报表快照时应单独设计。

401表示登录失效；403表示教师身份或操作权限不足；404表示具体班级不可访问；400表示查询无效；503表示数据库不可用。错误为JSON，无HTML登录跳转。列表、名单和CSV均no-store，Cookie相关响应带Vary: Cookie。

## 导出边界

- 独立新增export_class_roster权限，不冒用尚未实现的成绩导出。迁移classrooms.0002后执行init_roles，幂等更新保留teacher组，成员和班级授权保留。
- UTF-8 BOM、标准CSV引用与UUID文件名。用户可控单元格如以公式前缀开头，会加单引号；导出不包含成绩。
- 单次最多2000人，超限返回413 JSON，不能悄悄截断后提示成功。读取全部结束才发送文件，数据库异常不会产生半截CSV。
- 页面导出按钮重新请求服务器验证权限；失败清空旧名单，不把JSON错误保存成CSV。已下载到用户电脑的文件无法通过撤权收回。

## 其他模块接入

复用 `accounts.authentication.login_required_api` 和 `core.api.api_methods`。班级列表从 `classrooms.access.teacher_classes(request.account_user)` 开始限定，具体班级使用 `authorized_class(request.account_user, class_id)`。后者返回已验证班级，再依据它过滤本次业务数据，不能重新使用未经检查的请求班级编号。

未来成绩导出应传 `action=EXPORT_SCORES`，并增加成绩归属、最小返回字段和实际CSV入口测试，不能认为本次名单导出已经实现成绩功能。所有新搜索、详情、导出都必须复用检查；这些辅助函数不会自动保护未来新增的裸视图。

权限、组和授权直接查询数据库，不依赖长期缓存的has_perm结果。撤销角色/权限/授权、停用账号或班级影响下一次请求。当前不对已显示数据实时推送撤回，也不承诺中途撤权能取消已经开始执行的请求。维护停用再启用后的全设备永久撤销仍属第7组。

## 验收证据

- 122项后端完整回归通过，含第6组新增27项；22项DOM状态检查通过，含教师页面7项。
- 覆盖匿名、学生、维护员、超级用户、仅有授权无teacher组、跨班级/停用班级、角色/操作权限/班级授权撤销、转班、禁用账号、分页、CSV公式保护、超限拒绝和数据库失败。
- 真实内置浏览器使用独立测试库登录临时教师，只看到授权一班及其学生，CSV下载内容核对没有二班学生。页面已打开后撤销班级授权，再次导出被拒绝并清空旧名单，刷新为空授权列表。
- 未完成其他浏览器、100人并发、成绩接入、生产部署或维护后台验收。
