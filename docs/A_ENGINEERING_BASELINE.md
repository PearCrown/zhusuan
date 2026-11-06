# A侧工程接入核对与后续开发边界

日期：2026-11-06；真实负责人：开发者A；执行：Codex。

## 本次任务与授权

用户授权从GitHub的zhusuan项目获取内容，将做好内容上传；整体方向是完成A侧后与B集成。本次有限交付为真实工程接轨、现状与契约差异核对及上传。本记录不代表A侧全部开发完成，也不把后续候选范围当成已实现能力。用户没有要求每一步先等B操作；B复核安排用于最后集成评审，不阻塞当前只读核查与文档上传。

目标仓库：PearCrown/zhusuan；基线main提交：c1701817b069f151d181ef3efc34d12e459c85b5。通过GitHub连接器定位，读取远程AGENTS、README及分支后克隆到独立目录；新克隆Git状态无修改，建立codex/a-engineering-baseline-20261106分支。没有复用或清理他人工作目录。

原协作文档目录只有Markdown，原报告的“无工程”仅对那个目录成立，不能沿用为本仓库结论。这里已经存在可运行原型，后续沿用Django与PostgreSQL，不另起一套账号、鉴权或存档。

## 规范接轨

已读仓库AGENTS、README、PROGRESS及GAME_INTEGRATION、REVIEW、PUBLISH_REVIEW；检查仓库下仅有根AGENTS。新克隆在原协作工作区的同级目录，受共同父目录AGENTS约束；协作工作区内六份规范作为任务输入，不覆盖本仓库有效规则。

仓库规则要求保留Django会话/CSRF、固定用户ID、PostgreSQL及增量迁移，禁止重置数据、上传秘密或备份；每组交付前自主复查。原协作指南的client/server等目录为建议，按现有实现映射即可。补充分工仍待真实A/B共同确认，不因本记录擅自转移B的职责。

## 实际工程与目录映射

| 内容 | 已核对的实现入口 | 边界 |
|---|---|---|
| 技术栈 | requirements.txt、config/settings.py、package.json | Django固定5.2.18；README要求Python3.12、PostgreSQL17；HTML/CSS/JS同站，无独立前端服务器 |
| 身份与权限 | accounts/、classrooms/、core/ | 已有账号、班级与会话基础；本次未重跑后端验收 |
| 章节注册 | gameplay/chapters.py | 可信Chapter注册、重复ID拒绝；不是任意远程插件 |
| 进度与结算 | gameplay/models.py、services.py | 每账号每章唯一ChapterProgress；事务锁账号，校验revision/saveContext，服务端计分 |
| 题库 | gameplay/question_bank.py | 固定题库版本接入；正式内容后台尚缺 |
| 前端壳与通信 | templates/game.html、static/js/game.js、chapter-sdk.js | 单卡片章节及界面切换样例；不是两级地图/可行走横版场景 |
| API | gameplay/urls.py、views.py | 已有章节/进度/action与教师成绩/CSV路径 |
| 迁移与验证 | gameplay/migrations/、gameplay/tests/test_integration.py、scripts/*.test.cjs | 有迁移和测试源码；历史通过记录不等于本轮执行 |
| 环境与运维 | config/production.py、scripts/local_db.py、docs/CLOUD_DEPLOYMENT.md | 有云端准备；共同云端、100并发及浏览器矩阵仍未验收 |

原建议的client/maps、client/scenes没有现成对应实现；不能把game.js里的文字场景切换当作行走引擎。platform/chapters映射到gameplay/chapters.py；server/progress与client/save分别映射到gameplay/services.py和chapter-sdk.js；公共contracts尚无协作草案所要求的可执行schema。

## 真实接口与新草案的差异

现有接口文档是[GAME_INTEGRATION.md](GAME_INTEGRATION.md)。新协作草案是待落地目标，不是现有API规范。本轮没有改任何协议或数据库。

| 项目 | 仓库当前 | 协作草案目标/缺口 |
|---|---|---|
| 命令 | POST /game/api/chapters/{id}/action，action/revision/saveContext | requestId、idempotencyKey、expectedRevision等统一信封尚未实现；不可直接替换字段 |
| 操作 | move/talk/accept/answer/submit | acceptTask、enterTask、submitTask、deliverTask、clearLevel等尚无独立实体/命令 |
| 权威进度 | 服务端ChapterProgress，客户端只展示响应 | 服务端权威一致；assignment/instance/result/reward等分层尚缺 |
| 结算 | 每人每章一条，完成后submit返回原结果 | 多尝试不可变快照、最好/最新成绩、剧情/挑战/练习独立实例尚缺 |
| 模式 | 样例一个state含story/practice，chapter.kind标记integration_sample | 不是草案要求的mode/context隔离；不能声称已满足挑战协议 |
| 返回 | SDK失效隔离迟到响应，现有页面状态切换 | 无位置/朝向/摄像机/input lock/returnToken协议 |
| 奖励与出口 | 样例提交完成 | 无独立交付、一次性奖励账本与服务端出口判定 |

兼容示例：现有SDK调用dispatch('move', {scene:'workshop'})，由SDK附加当前revision及saveContext。不能把草案的operation='enterTask'直接发送现有action端点。后续应保留sample-counting及其schema_version=1和旧题库；新能力通过独立内容/适配入口增量加入，涉及持久数据时先提迁移与兼容样例，再落实现。不得把新运行器结果写入旧样例score或重置旧档。

## 下一步开发顺序

以下是A侧接轨后的建议任务拆分，尚无实现或验收结论；应逐张登记实际允许文件和证据。

1. A-003最小契约与场景宿主边界：沿用现有身份/SDK，设计独立Demo注册、上下文、返回及输入锁边界；写成功、拒绝、重复、取消/超时示例，与B的任务/Runner对接。先交契约差异，不改旧样例。
2. A-004地图与横版场景：一个章、一个关、一个NPC、任务点及出口，接入B提供的对话/运行器；缺失B实现时用明确标注的fixture验证边界。
3. A-005正式状态与恢复：增量迁移、任务实例/作品快照、服务端核验、返回/刷新/冲突/账号隔离；永久完成不能靠客户端标记。
4. 集成及验收：合并B实际交付，保留旧样例回归，跑真实PostgreSQL、浏览器闭环，后续再做并发与云端环境验收。

不凭目录或历史测试计数宣布以上完成；不在这次文档上传中暗中引入业务或部署。

## 命令与本次证据

本次实际执行：GitHub仓库/分支查询与文件读取；git clone；git status --short --branch；git rev-parse HEAD；git log -1；rg文件检索；Get-Content读取代码与规范；git switch -c；git diff --check及文档链接/发布文件检查。原始摘要：远程仅查询到main；基线c170181；克隆初始状态为main...origin/main且无修改。

README已登记安装、迁移、启动、测试命令；这里只引用入口，不另维护第二套启动说明。本克隆未准备虚拟环境、数据库或本地秘密配置；安装、后端/UI测试、浏览器与负载测试均未执行。本次只改变文档，不沿用历史228/45项作为新测试结果，也不连接旧开发数据库。

## 交接

本次只新增本文件，更新PROGRESS.md、docs/REVIEW.md、docs/PUBLISH_REVIEW.md。运行方式为阅读报告与既有README；接口变化无；数据库变化无；未启动服务，无运行实例需要同步。文档链接与差异/发布范围复核后上传独立分支，提交和PR结果以GitHub核验为准。

未完成的是A侧业务开发、B成果接入与云端/容量等验收；不是等待B才能继续查资料。下一次从上述最小契约任务接续，任何实际实现继续遵循仓库自主复查规则。
