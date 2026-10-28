# 账号接口：当前交付

当前开放CSRF获取、学生注册、登录、身份查询、退出。路径**不带末尾斜线**；默认同站访问，使用Cookie与CSRF。生产必须通过HTTPS。第5组账号页面已接入，入口为GET /。

第6组另提供 `/teacher/` 和受保护的班级列表、学生名单及名单CSV接口，详见 [TEACHER_ACCESS.md](TEACHER_ACCESS.md)。第7组HTML维护页见 [MAINTENANCE.md](MAINTENANCE.md)，最新本地后端137项、DOM状态24项通过；下方早期验证数为历史记录。

第8组新增POST `/auth/password/change`、`/auth/password/reset`，字段、一次性凭据、限流及失败语义见 [PASSWORDS.md](PASSWORDS.md)。最新全套157项通过，后续密码/维护38项定向及33项DOM检查通过；上方各组数字为阶段历史。

## 通用返回

成功：`{"ok": true, "data": {...}}`

失败：`{"ok": false, "error": {"code": "固定错误代码", "message": "用户提示", "fields": {"字段": ["原因"]}}}`

`fields`仅在有字段错误时出现。响应禁止缓存。不要把message文字作为程序判断条件，应根据HTTP状态和code处理。

## GET /auth/csrf

返回200及`data.csrfToken`，同时设置CSRF Cookie。后续修改请求携带Cookie，并通过`X-CSRFToken`提交返回的token。此token不是登录凭据，不创建登录会话；不要通过URL传递token。

缺少或错误的CSRF信息、跨站来源不通过时，注册接口返回403、`csrf_failed`，不返回内部失败原因。

## POST /auth/register

请求头：`Content-Type: application/json`，可显式指定`charset=utf-8`。请求体最多8192字节，只允许三个字段：

| 字段 | 类型 | 规则 |
| --- | --- | --- |
| username | string | 3—32位，规范化后为英文字母、数字、下划线、点或短横线，以字母或数字开头 |
| displayName | string | 必填，去首尾空白后1—60个可见字符，可使用中文 |
| password | string | 必填，12—128个字符；不允许纯数字、常见密码或与账号资料过于相似；不去空格、不改变Unicode形式 |

不接受`role`、`is_staff`、`is_superuser`、`groups`、`user_permissions`、`userId`、`classId`、`email`、`phone`或其他多余字段。非文字不自动转换成文字。拒绝重复JSON键、非标准NaN/Infinity及无效字符编码。

成功201：

```json
{
  "ok": true,
  "data": {
    "userId": "服务器生成的UUID",
    "username": "student01",
    "displayName": "小明",
    "role": "student"
  }
}
```

- 账号与student组分配在一个事务中完成；失败不能留下半成品账号。
- 不绑定班级，不授予维护权限，不自动登录。
- 密码强度使用Django验证能力，额外拒绝全空白密码；保留正常密码的首尾空格。公开提示采用固定中文文案，避免验证器原始错误泄露输入。
- 前端确认密码已在页面实现，不作为注册接口的重复字段。

| 状态 | code | 含义 |
| --- | --- | --- |
| 400 | validation_error | 字段缺失、类型、格式或密码强度错误 |
| 400 | invalid_fields | 包含不允许的字段 |
| 400 | invalid_json / invalid_request | 请求内容或长度无效 |
| 403 | csrf_failed | 缺少有效CSRF信息或来源不通过 |
| 405 | method_not_allowed | 使用了不支持的方法；响应含Allow |
| 409 | username_taken | 规范化后的用户名已被使用，包括并发冲突 |
| 413 | request_too_large | 请求体超过限制 |
| 415 | unsupported_media_type | 非UTF-8 JSON请求 |
| 429 | rate_limited | 请求过于频繁，按Retry-After秒数稍后再试 |
| 503 | registration_unavailable | 学生组缺失或其权限被错误配置 |
| 503 | service_unavailable | 数据库或限流服务不可用，失败时不会跳过限制 |
| 500 | internal_error | 未预期错误，响应和日志不回显请求数据 |

其他不安全方法若缺少CSRF，也可能先得到403。注册成功后的重复点击会得到409；页面应进入登录步骤，不自动重试注册。

## 前端接入方式

1. 同站GET `/auth/csrf`，保存返回token，浏览器接收Cookie。
2. POST `/auth/register`，发送三个字段及`X-CSRFToken`，使用`credentials: "same-origin"`。
3. 201后提示注册成功，切换登录表单；400展示字段提示；409请用户换名或前往登录；429等待，不循环重试。
4. 不把密码写入日志、网址、浏览器持久存储；提交时即清空密码输入。页面属于第5组，已实现。

## 限流与运行限制

- 在CSRF解析表单前，先对标记为JSON接口的请求检查媒体类型、编码和声明大小；错误类型返回415、过大返回413，不读取或解析这些表单。这些协议预检拒绝发生在CSRF及数据库限流前，不创建账号、不消耗注册计数。有效JSON请求仍需通过CSRF，不能因此绕过验证。
- 默认每个来源IP、每个固定600秒窗口最多120次注册尝试，包括通过协议预检及CSRF后的无效字段请求。默认值考虑同一教学班共享校园IP，但尚未验证实际部署容量。
- 可用`REGISTER_RATE_LIMIT_MAX_ATTEMPTS`和`REGISTER_RATE_LIMIT_WINDOW_SECONDS`调整。多个进程共享PostgreSQL原子计数，重启网页进程不会重置计数。
- 使用连接来源`REMOTE_ADDR`，忽略客户端自报的Forwarded/X-Forwarded-For。反向代理部署前必须设计可信代理地址来源；不能直接照信这些请求头，否则可伪造IP。未配置时代理后的用户可能共享同一额度。
- 固定窗口边界允许相邻窗口的突发流量，不能当作滑动窗口或全站抗攻击能力。部署层仍需限制连接、请求体与并发；本次不代表100人验收完成。
- 窗口使用系统时钟，多个主机部署前应确保时间同步。
- 持久化键使用带密钥的摘要，不保存原始IP；这不等于完全匿名化。过期记录可保留到清理时。
- 运维时执行`manage.py prune_rate_limits`清理过期超过24小时的记录；第12组安排运行方式，目前未创建定时任务。
- 限流在用户写入事务之前提交，不得无评估地启用整个请求的ATOMIC_REQUESTS，否则失败请求的计数行为可能变化。

## 本轮验证范围

最新95项后端自动化测试在独立PostgreSQL测试库通过，覆盖原注册回归，以及登录、退出、会话保存/读取故障注入、过期、停用、账号切换、密码变化、来源校验、独立登录限流和页面缓存/方法检查。另有15项不连接数据库的DOM状态检查。

另通过临时测试服务的真实HTTP请求验证CSRF、成功注册、同名冲突、拒绝提权字段及数据库身份；临时账号已清理，开发库未添加验收账号。第5组在内置浏览器验收注册、登录、刷新、身份更新、退出及服务中断；其他浏览器、生产发送/部署、完整游戏平台或100人负载未验收。

第4组另验证了真实HTTP登录、服务重启后的身份恢复、角色/班级授权变化后的身份刷新、账号切换、旧Cookie重放拒绝、退出、旧CSRF拒绝和停用后的下一请求拒绝。数据库故障使用自动化故障注入验证，未人为中断共享开发数据库。

## POST /auth/login

请求为UTF-8 JSON，仅允许`username`、`password`。用户名采用注册时的相同规范化规则；密码不去空格、不改变Unicode形式，不重新应用注册强度规则，避免后来提高策略时锁住已有账号。请求长度、字段类型和编码仍须合法。

成功200：`data`包含`user`（身份结构见下方）和`csrfToken`。浏览器通过HttpOnly Cookie接收会话凭据，JSON中没有会话密钥或密码。

- 未知账号、错误密码、停用账号统一返回401、`invalid_credentials`及“账号或密码错误”。
- 每次成功登录替换当前浏览器会话，包括同账号再次登录；切换账号不会继承前账号的会话数据。
- 在密码验证后，锁定用户行并重新核对账号启用状态和密码摘要，防止验证过程中状态改变仍建立旧凭据会话。
- 错误凭据不会替换当前已经登录的身份。基础设施故障或响应丢失后不能猜测是否仍登录，应重新GET `/auth/me`确认。
- 默认会话从本次登录起绝对8小时有效。读取身份不延长；关闭浏览器不主动注销。可用`SESSION_AGE_SECONDS`调整。
- 登录时轮换CSRF信息。前端必须使用成功响应的新token，或重新GET `/auth/csrf`；不能一直使用登录前的token。
- 会话写入发生在响应处理阶段；保存失败时返回503，不能把原先的200成功内容返回给客户端。并发移除会话导致写入中断时返回401。

登录限流与注册独立：默认同一来源IP每600秒300次，来源IP与规范化用户名组合每600秒10次，成功/失败尝试均计数。前一层也计入通过协议/CSRF后的无效输入；后一层在用户名校验后计数。未知账号采用相同计数规则，不能用更换大小写绕过。限制命中返回429及Retry-After。

可配置`LOGIN_IP_RATE_LIMIT_MAX_ATTEMPTS`、`LOGIN_ACCOUNT_IP_RATE_LIMIT_MAX_ATTEMPTS`、`LOGIN_RATE_LIMIT_WINDOW_SECONDS`。仍为固定窗口，不能防御所有分布式尝试；与注册共用可信来源部署边界。

## GET /auth/me

已登录返回200，`data`为：

```json
{
  "userId": "固定UUID",
  "username": "student01",
  "displayName": "小明",
  "roles": ["student"],
  "classId": null,
  "teachingClassIds": []
}
```

- `roles`是已分配的项目组名列表，可同时含student、teacher；不包含组外额外标记。教师不需要先成为维护人员，也不应因为没有student组就被禁止游玩。
- `classId`是当前有效班级，未分班或班级停用时为null；`teachingClassIds`仅在当前具有teacher角色时返回有效授权班级。
- 每次请求按当前数据库读取身份和授权关系，不把角色缓存进会话。返回的信息用于界面展示；第6组教师列表、名单和CSV另行执行服务端角色、操作权限及班级范围检查，不能凭此信息放行。
- 无登录、会话过期、无效Cookie、无效存储身份、密码摘要失效或账号停用返回401、`authentication_required`，不跳转HTML登录页。
- 停用账号呈递的会话会被移除。第7组维护操作另行递增session_revision，旧设备认证摘要永久失效，账号重新启用也不会恢复，包括停用期间未访问的令牌。直接SQL或旧手工改状态不自动具备该保证，须复用维护服务。
- 账号状态、会话或身份读取数据库失败返回503，不返回旧身份作为替代。

支持HEAD。响应禁止缓存，并随会话访问设置Vary: Cookie。

## POST /auth/logout

请求为UTF-8 JSON空对象`{}`，需要有效CSRF，不接受目标用户、会话编号或其他字段。成功200：`data.loggedOut`为true，并返回轮换后的`csrfToken`。

- 服务端删除当前会话，清除Cookie；复制的同一Cookie随后无法读取身份。
- 不影响其他设备的独立会话。所有设备退出属于后续维护能力。
- 已退出或过期时，只要请求格式和CSRF有效，重复退出仍返回200。每次使用最新token。
- GET不会执行退出。删除会话失败返回503，不能显示“已退出”；前端可重试或查询当前身份。

## 其他模块复用登录检查

使用`accounts.authentication.login_required_api`装饰需要登录的JSON视图。该装饰器独立提供安全JSON错误处理，并设置`request.account_user`为经过检查的当前用户；无需另记装饰器顺序。业务数据归属只使用该用户的pk。

用`core.api.api_methods`声明允许的方法，例如GET、HEAD或POST；请求方式预检会在CSRF解析之前拒绝不支持的方法，读接口不会因错误POST表单而进入解析。若接收JSON修改请求，再加`core.api.requires_json_body`声明。装饰器元数据通过wraps保留；不要使用关闭CSRF或HTML跳转式登录检查来解决API接入。

会话保存错误保护继承Django的SessionMiddleware，仅补充API失败响应，不另造认证系统。新受保护API同样会被识别；页面视图继续使用框架行为。

框架依据：https://docs.djangoproject.com/en/5.2/topics/auth/passwords/ 和 https://docs.djangoproject.com/en/5.2/ref/csrf/ 。
