# 铸算·华夏纪 · 账号与游戏框架原型

这是《铸算·华夏纪》的可运行开发原型，包含账号权限、教师与班级管理、可玩的章节接入样例，以及为云端部署准备的配置和数据维护工具。采用 **Python 3.12、Django 5.2 LTS、PostgreSQL 17、HTML/CSS/JavaScript**；网页和后端由同一服务提供，不需要单独启动前端开发服务器。

**当前可以在自己的电脑上运行；尚未部署共同云端，也不是完整正式游戏。真实短信和邮件发送默认关闭。** 代码下载、GitHub仓库与线上平台是不同的东西：Fork或clone只获得代码，仍需按下文安装环境和准备数据库。

## 当前能做什么

| 模块 | 已实现 | 当前边界 |
| --- | --- | --- |
| 账号 | 学生注册、用户名密码登录、退出、修改密码、固定用户ID | 教师身份由维护人员分配，注册时不能自选 |
| 密码恢复 | 维护人员核实后发放短时一次性凭据，本人设置新密码 | 维护账号不走普通账号恢复入口 |
| 角色与维护 | 学生、教师、受限维护人员分离；班级、归属、教师授权和变更审计 | 无默认管理员、共享教师密码或批量维护工具 |
| 可玩样例 | 章节选择、NPC对话、接任务、城门/算坊切换、逐题保存、提交计分 | 占位剧情与单卡片地图；每账号样例只结算一次 |
| 存档与扩展 | 服务器数据库保存、刷新恢复、章节注册、进度/成绩回调、题库版本接口 | 完整题库后台、正式剧情、美术和多次练习成绩策略待做 |
| 教师工作区 | 授权班级、当前名单、历史提交成绩；名单与成绩分别导出CSV | 成绩按提交时的班级记录，转班不移动旧成绩 |
| 验证码 | 首次绑定、验证码登录、找回密码的本地开发流程 | 尚未接真实供应商；更换/解绑和旧地址通知待做 |
| 云端准备 | 独立生产配置、数据库就绪探测、过期挑战分批清理 | 还需真实服务器、域名、TLS、代理和静态资源联调 |
| 备份恢复 | 数据库归档与完整性清单、恢复到独立空库 | 已做本机演练；未做真实云端异地加密灾备验收 |

主线剧情任务与计分练习可以作为并行分支发展。现在三道题的路线只用于验证接入，不表示正式主线必须刷题。更新题库应发布新版本并保留旧版，不能覆盖玩家已有存档引用的题目。

## 启动后怎么体验

| 页面 | 地址 | 使用条件 |
| --- | --- | --- |
| 账号中心 | `/` | 访客可注册学生账号；登录后查看身份、修改密码和进入样例 |
| 游戏接入样例 | `/game/` | 登录账号即可游玩，教师也能玩 |
| 教师工作区 | `/teacher/` | 必须有教师角色、相应操作权限和明确班级授权 |
| 受限维护台 | `/maintenance/` | 必须由可信终端预先授予维护身份 |
| 人工密码恢复 | `/password/reset/` | 先联系维护人员核实本人，获得有效凭据 |
| 联系方式验证 | `/verification/` | 当前实际发送关闭，会提示使用用户名密码或联系维护人员 |

样例路线：**登录 → 进入接入样例 → 进入章节 → 与NPC对话 → 接受任务 → 前往算坊 → 每题保存答案 → 返回城门 → 提交任务**。刷新后重新进入章节，进度与已提交结果从服务器恢复。教师登录后选择授权班级，再点击“查看本班成绩”。未分班提交的成绩只保留个人结果，不自动归到以后加入的班级。

![可玩样例结算预览（虚构验收数据）](docs/images/game-demo.png)

## 下载后不会自动得到什么

每个人默认使用自己的数据库、账号和密钥，彼此数据不共享。仓库不包含真实账号、`.env`、`.env.test`、数据库、会话、管理员凭据、PostgreSQL程序、虚拟环境、Node依赖或备份。测试中的样例密码不是可登录的共享账号，截图使用临时虚构数据。

GitHub Pages不能直接运行本项目的Django后端和PostgreSQL。共同云端需要另行部署应用和数据库；未来前端继续使用同站相对API地址，无需为每个接口逐一替换localhost。

## 首次安装：Windows本地独立方案

需要 Git、稳定版 Python 3.12，以及 PostgreSQL 17 的Windows x64二进制程序。Node.js只在运行页面开发检查时需要，启动网页不需要Node。

### 1. 下载代码并准备Python环境

```powershell
git clone https://github.com/PearCrown/zhusuan.git
cd zhusuan
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

如果使用自己的Fork，将clone地址替换为你的仓库地址。也可以下载ZIP并解压，在项目目录打开PowerShell，再执行创建环境和安装依赖两条命令。后续命令不需要手动激活虚拟环境。

### 2. 准备独立数据库

从 [EDB官方Windows二进制下载页](https://www.enterprisedb.com/download-postgresql-binaries) 获取PostgreSQL 17。解压到项目 `.local/postgres/`，确保以下路径存在；不要把二进制文件提交Git：

```text
zhusuan/
  manage.py
  .local/
    postgres/
      pgsql/
        bin/
          pg_ctl.exe
          initdb.exe
```

然后执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\local_db.py start
```

首次启动会自动生成仅本地保存的随机密钥、数据库密码和 `.env`，创建项目专用数据库及普通应用账号，不安装Windows服务。默认只监听 `127.0.0.1:55432`，**不是**PostgreSQL常见的5432端口。此方案不要提前复制一个秘密为空的 `.env`；若文件已存在，脚本不会覆盖它。已有数据库也不会被重置。

### 3. 建表、初始化角色并启动网页

```powershell
.\.venv\Scripts\python.exe -X utf8 manage.py migrate --noinput
.\.venv\Scripts\python.exe -X utf8 manage.py init_roles
.\scripts\start.ps1
```

打开 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)，自行注册学生账号、登录并退出。窗口内按Ctrl+C停止网页服务。登录后点击“进入接入样例”即可游玩；教师和维护入口需要额外授权，操作见下文。

`init_roles`可重复执行，不创建用户、不改变组成员或班级关系；它会把student、teacher、maintainer三个保留组的权限恢复为代码定义。不要给这些保留组随意增加权限。

## 以后再次启动

在项目目录打开PowerShell：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\local_db.py start
.\scripts\start.ps1
```

打开 [http://127.0.0.1:8000/](http://127.0.0.1:8000/)。使用 `--noreload` 运行，修改Python代码或模板后需要停止并重新启动网页服务。

```powershell
# 单独检查配置和数据库，均不建表
.\.venv\Scripts\python.exe -X utf8 manage.py check
.\.venv\Scripts\python.exe -X utf8 manage.py check_db
# 停止本地数据库
.\.venv\Scripts\python.exe -X utf8 scripts\local_db.py stop
```

`start.ps1` 如被系统执行策略阻止，可直接运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 manage.py runserver 127.0.0.1:8000 --noreload
```

## 使用已有PostgreSQL / macOS或Linux

Windows独立数据库脚本不适用于其他系统。已有数据库或其他系统应自行准备PostgreSQL 17、专用普通登录角色及其拥有的空数据库；应用角色不要使用数据库超级用户。复制 `.env.example` 为 `.env`，填写DB_*及至少50字符的随机DJANGO_SECRET_KEY。数据库密码也必须自行生成；DB_PORT应改成实际监听端口。

macOS/Linux命令参考（这些系统尚未逐项实机验收）：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
# 在本地编辑.env，配置已准备好的数据库和随机密钥，再继续：
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py init_roles
.venv/bin/python manage.py check
.venv/bin/python manage.py check_db
.venv/bin/python manage.py runserver 127.0.0.1:8000 --noreload
```

Windows使用已有数据库时，使用 `.venv\Scripts\python.exe` 执行上述manage.py命令，不要运行独立数据库控制脚本。可在自己的终端用以下命令生成新密钥，复制到自己的.env中，切勿粘贴到公共仓库或聊天：

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(64))"
```

`.env`、`.local`、`.venv` 均不提交。其中 `.local` 包含数据库数据和仅本机使用的初始化凭据，不可公开分享。若 `.env` 已存在，启动脚本不会覆盖；若修改了数据库密码，必须在数据库中同步修改，不能指望脚本自动重置。

## 如何准备教师和维护人员

先在账号中心注册自己的维护专用账号，再由项目负责人在可信本机终端执行下列命令，将 `your_username` 替换为实际用户名，然后重新登录：

```powershell
.\.venv\Scripts\python.exe -X utf8 manage.py provision_maintainer your_username
```

命令不创建账号、不设置密码，也不自动开启Django管理站点。维护人员进入维护台后可以创建班级、分配教师身份、安排学生归属和授权教师班级。**教师身份与班级授权是两件事，缺一不能读取班级数据。** 维护人员也不会自动获得所有班级成绩权限。

生成恢复凭据成功后，先复制凭据，再点击该页的“打开重置密码页面”；不需要退出登录或手输地址。具体步骤见 [维护台说明](docs/MAINTENANCE.md)；可选的手动教师演示见 [LOCAL_DEMO.md](docs/LOCAL_DEMO.md)。不要通过修改浏览器页面、localStorage或客户端role字段获得身份，服务器不会信任这些值。

## 已有版本如何升级

1. 保存自己的代码改动，并备份数据库及环境配置，先阅读本次说明。
2. 获取新代码，安装requirements.txt中的依赖；若用自己的Fork，需自行同步上游。
3. 执行下列增量更新，再重启网页服务。不要删库、删迁移文件或重新注册用户来升级。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -X utf8 manage.py migrate --noinput
.\.venv\Scripts\python.exe -X utf8 manage.py init_roles
.\.venv\Scripts\python.exe -X utf8 manage.py check_db
.\scripts\start.ps1
```

`init_roles`会校准保留组权限，不改变现有成员与班级关系。用户名、固定用户ID和已有业务数据通过数据库保留；版本升级不应靠覆盖存档解决冲突。

## 备份、恢复与未来云端

本地备份当前配置数据库：

```powershell
.\.venv\Scripts\python.exe -X utf8 manage.py backup_database --output backups/platform-20261028.dump
```

文件名每次应唯一。归档及其完整性清单包含或关联敏感资料，**不上传GitHub或公共群聊**。恢复工具只写入另一个独立普通账号拥有的空数据库，不覆盖当前库；完整步骤与目标确认要求见 [备份恢复说明](docs/BACKUP_RESTORE.md)。数据库备份不包含应用密钥，密钥须另行安全保管。

云端使用 `config.production` 和非秘密模板 [.env.production.example](.env.production.example)，通过服务器环境注入实际配置；应用不会自动读取名为.env.production的文件。生产配置要求HTTPS、安全Cookie、明确主机与站点来源、数据库证书校验；内存消息发送器禁止用于生产。代理、真实客户端IP、静态资源及多实例连接数需按最终服务器联调，见 [云端部署说明](docs/CLOUD_DEPLOYMENT.md)。本地runserver和Windows数据库启动脚本不用于生产。

`/health/live/`只表示网页进程存活；`/health/ready/`检查数据库连接。两者都不能证明迁移完整、业务闭环或100人容量，发布时仍须单独检查。

## 验证码为什么收不到

默认 `CONTACT_MESSAGE_BACKEND=disabled`，首页不展示未开放的验证码入口；直接打开验证页仍会明确提示尚未开放。代码中的memory发送器仅为显式开启的开发测试工具，不发送真实消息，不公开验证码读取接口，生产模式会拒绝启用它。不要把开发模式当成正式短信或邮件服务。

本地流程已经实现5分钟有效、连续输错5次锁定、一次性消费、用途/浏览器/账号状态绑定和限流。绑定需要当前密码验证，找回只使用已验证联系方式，不能用旧User.email字段或未验证地址找回。详情见 [验证码流程](docs/CODE_FLOWS.md)。

## 开发检查与验收证据

完整后端最近一次 **228项通过**；之后新增不完整清单失败清理检查，备份专项 **7项通过**。页面状态 **44项通过**；这些DOM检查不等于跨浏览器验收。详细阶段记录见 [PROGRESS.md](PROGRESS.md)。

本机另做了真实PostgreSQL隔离恢复演练：从空库建表并填入虚构数据，备份恢复后19张表所有行一致，密码、固定ID、会话、游戏成绩和教师范围可用；非空目标拒绝覆盖。临时库和角色已清理，开发数据未被覆盖。

运行后端测试前，先准备只保存可丢弃数据的独立测试库。本项目Windows自有本机数据库可执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\setup_test_db.py
.\scripts\test.ps1
```

测试使用独立普通角色及 `config.test_settings`，每轮开始前核对并清理测试库残留；**不要在测试库放真实账号，不要同时对该库运行手动验收服务**。其他数据库环境由维护人员独立准备测试角色和数据库。普通 `manage.py test` 会被隔离保护拒绝。

Node.js只用于可选页面检查，网页运行不依赖Node。使用稳定Node.js 22或24：

```powershell
npm ci
npm run test:ui
```

尚未完成：真实云端部署与TLS/代理联调、真实消息发送、异地加密备份、100人负载、Chrome/Edge/Firefox/Safari完整矩阵、依赖漏洞审计。浏览器内成绩显示已验收，成绩CSV后端已检查，第9组浏览器实际下载仍需补验。`pip check`和锁定依赖不等于漏洞扫描；本项目当前不声明生产就绪。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 找不到Python 3.12 | 安装稳定版3.12，避免使用Windows商店占位命令 |
| 缺少pg_ctl.exe | 检查上文.local/postgres/pgsql/bin解压路径 |
| 缺少密钥或数据库密码 | 独立方案不要提前创建秘密为空的.env；已有数据库按模板填写，勿删库重建 |
| 数据库无法连接 | 启动数据库并核对实际端口；默认独立方案为55432，运行check_db检查 |
| 注册暂不可用 | 核对migrate与init_roles已成功执行 |
| 看不到维护或教师入口 | 检查服务器分配的身份及班级授权，没有默认账号或自动提权 |
| 没有教师成绩 | 学生需先提交，教师需被授权该提交所属班级；名单归属与历史成绩归属可能不同 |
| 修改代码后页面还是旧版 | 停止并重新启动网页服务，再刷新浏览器 |
| PowerShell阻止.ps1 | 直接使用上文python manage.py启动/测试命令，无需修改全局执行策略 |

## 进一步阅读

- [密码恢复入口与导航说明](docs/NAVIGATION.md)
- [阶段记录](PROGRESS.md) · [自主复查](docs/REVIEW.md) · [发布审查](docs/PUBLISH_REVIEW.md)
- [账号API](docs/API.md) · [数据与角色](docs/DATA_MODEL.md) · [教师范围](docs/TEACHER_ACCESS.md)
- [维护台](docs/MAINTENANCE.md) · [改密与人工恢复](docs/PASSWORDS.md)
- [联系方式基础](docs/CONTACTS.md) · [验证码流程](docs/CODE_FLOWS.md)
- [章节、存档及题库接入](docs/GAME_INTEGRATION.md)
- [云端部署](docs/CLOUD_DEPLOYMENT.md) · [备份恢复](docs/BACKUP_RESTORE.md)

首次第1—6组的发布记录保留在 [RELEASE_REVIEW.md](docs/RELEASE_REVIEW.md)，其中“未实现”描述为当时历史范围；当前能力和限制以上文为准。
