# SceneHost v1：A场景与B运行器的接入边界

状态：A-003客户端实现已交付，供A/B集成评审；尚未接入正式地图或B运行器。HTTP、数据库及旧样例协议保持原样，不把本接口视为已冻结的全平台契约。

## 宿主负责的行为

先加载`static/js/scene-host.js`，浏览器得到`HuaxiaInputLocks`和`HuaxiaSceneHost`。本文件不自动加载到旧`/game/`，因此不会改变既有玩家存档或样例流程。

输入锁使用对象身份配对释放。同一个场景的对话、任务和其他面板共用一个locks实例；移动代码每帧检查`locks.locked`，按键集合由clearInput清空。释放任务锁不会解锁仍打开的对话。没有releaseAll入口。

宿主构造参数：

| 字段 | 要求 |
|---|---|
| context | chapterId、levelSessionId、sceneId、sessionEpoch四个非空字符串；每项最多128字符。只用于当前页面关联，不是鉴权凭据 |
| scene | walkRange:[min,max]为0—1的可走区；spawn:{x,facing,cameraX}为合法安全点；facing是left/right，cameraX为0—1 |
| locks | 当前场景共享的HuaxiaInputLocks实例 |
| clearInput() | 同步释放所有按下键及拖拽状态，不写存档 |
| readProgress({context,signal}) | 异步返回服务端最新progress，必须含匹配chapterId及非负安全整数revision |
| restoreScene({context,snapshot,progress,signal}) | 等待资源就绪，先更新NPC/出口和任务栏等展示，再恢复位置/朝向/摄像机；副作用前检查signal，异步等待后再次检查 |
| callbacks | 可选draftChanged、operationCompleted、submitRequested、exitRequested、fatalError函数；收到{instanceId,generation,value} |
| timeoutMs | 返回读取和恢复合计超时，默认12000ms，允许1—120000整数 |

构造参数的外层context/scene数据会复制冻结。坐标是归一化设计值；场景实现负责转成像素。超出当前可走区或摄像机范围的返回坐标回安全出生点。NaN、无穷值、非法朝向拒绝进入。

## B运行器的最小适配

`runner.mount(element, {instanceId,config,draft,signal}, callbacks)` **同步**返回`{exportDraft,pause,dispose}`三个函数。资源可异步加载，但不能返回Promise；异步过程必须检查signal及自身挂载代次。dispose必须可重复且释放自己的DOM、监听器、拖拽与计时器，不清除其他宿主内容。

`beginTask({instanceId,runner,host,config,draft,snapshot})`清空按键并加任务锁，返回一个内存returnToken。相同活动instanceId重复进入只复用原token，不重新挂载；其他实例在前一实例关闭前被拒绝。instanceId最终应来自正式任务协调器；当前仓库没有该服务，测试中的ID仅为虚构fixture。

回调仅报告意图。本地operationCompleted不等于正式通过；submitRequested由任务协调器调用服务端保存/核验，宿主不会依据pass/score写任何进度。exitRequested也不自动关闭：B先处理未保存作品、确认保留/丢弃及提交中的查询，再明确调用returnToScene。`exportDraft(token)`只取运行器草稿，不代替云保存。

## 返回、取消与重试

`await host.returnToScene(token)`按顺序清空输入、停止并卸载运行器、读取最新进度、校正位置、恢复场景、再次清空输入、释放自己的任务锁。只有restoreScene完成后才可行走。同一返回中的重复调用复用Promise；成功后重复返回不再传送或读取。完成处理后调用`finishReturn(token)`，再进入下一任务实例。

读取失败、非法进度、恢复失败和超时会拒绝Promise并保持任务锁，避免半恢复时走动。界面显示重试/返回选关选项：重试用原token调用returnToScene，不重发提交、不重新挂载旧运行器。返回选关时先invalidate，再由场景管理器卸载旧场景。宿主不把网络超时判成任务失败。

`invalidate()`用于切账号、退出关卡、替换场景：使旧token失效、中止返回、卸载运行器、释放自己的锁及清空输入。构造时绑定的context不复用到新会话，应dispose后创建新宿主。pagehide或页面隐藏会自动invalidate；重新可见时由应用验证会话、重新读取服务端数据并重建场景。`dispose()`额外移除生命周期监听，可重复调用。

超时/失效会abort提供给readProgress/restoreScene的signal。宿主不再接受迟到结果；提供器自身也必须在写DOM或应用资源前检查signal，不能指望宿主撤回提供器已执行的副作用。服务器已受理的提交不会被这些取消操作回滚。

returnToken是不可复制的内存对象，只用于当前宿主身份检查；不放URL、localStorage、存档或网络。它不证明用户身份、交互距离、正式实例归属或通关资格，未来服务端仍需逐项核验。

## 与现有SDK组合示例

以下是接线示例，sceneRenderer、BRunner和serverInstance来自未来集成模块，不是本仓库现成对象。当前sample-counting没有instance服务，不得伪造ID当成云端验收。

```javascript
const client = new HuaxiaChapterClient(chapterId); // 此专用读取客户端不注册自动渲染回调
const locks = new HuaxiaInputLocks();
const host = new HuaxiaSceneHost({
  context: {chapterId, levelSessionId, sceneId, sessionEpoch},
  scene: {walkRange: [0.05, 0.95], spawn: {x: 0.2, facing: "right", cameraX: 0}},
  locks,
  clearInput: () => sceneRenderer.clearPressedKeys(),
  readProgress: async ({signal}) => {
    const {progress} = await client.load();
    signal.throwIfAborted();
    return progress;
  },
  restoreScene: async ({snapshot, progress, signal}) => {
    await sceneRenderer.loadAssets(signal);
    signal.throwIfAborted();
    sceneRenderer.applyProgressAndPosition(progress, snapshot);
  },
  callbacks: {
    submitRequested: report => taskCoordinator.requestSubmit(report),
    exitRequested: report => taskCoordinator.confirmExit(report),
  },
});
const token = host.beginTask({
  instanceId: serverInstance.instanceId, runner: BRunner, host: runnerElement,
  config: serverInstance.config, draft: serverInstance.draft,
  snapshot: sceneRenderer.capturePosition(),
});
// B确认退出，且草稿/提交状态已处理后：
await host.returnToScene(token);
host.finishReturn(token);
// 切账号或离开关卡前：
client.invalidate();
host.dispose();
```

## 验证及限制

在README登记的`npm ci`后执行`npm run test:ui`。本轮62项通过，其中17项为SceneHost边界测试，使用虚构进度和mock运行器。覆盖输入锁、位置校正、最新进度顺序、重复进入/返回、非法数据、失败重试、超时、迟到回调、卸载异常、异步mount误用和页面生命周期。

自主复查修复：运行器卸载失败发生在读取前时，中止Promise可能无处理，现已提前处理拒绝并补回归；返回失败后也保持旧运行器回调关闭。新增可见性测试首次失败源于测试在关闭窗口后再清理第二宿主，已调整清理顺序，62项最终通过。

没有改后端或数据库，未执行后端、真实浏览器或100人测试；未实现正式地图/场景、任务协调器、永久状态或奖励账本。B尚未接入正式运行器，mock通过不代表联调或云端验收通过。
