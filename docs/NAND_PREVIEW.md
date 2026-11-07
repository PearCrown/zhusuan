# C-003-A · NAND 接线样例

基线 `32a6890`，SceneHost v1。独立预览供统筹和开发者 B 复核。正式游戏、C-002 试放、公共脚本、依赖和后端均未修改。

## 打开与操作

在已有 8767 本地静态服务打开 [NAND 接线台](http://127.0.0.1:8767/nand-preview.html)。若服务已停，从仓库根目录按 [SCENE_ART_PREVIEW.md](SCENE_ART_PREVIEW.md) 的原命令启动，再打开 NAND URL。同一个服务可同时访问两个预览。无需登录、安装依赖或启动 Django。

1. 选择「开始接线」。先选 A、B 或 Q，再选目标 IN1、IN2 或 Y；未选源时，操作已连线的目标可以拆线。
2. 正确连接是 A/B 分别接 IN1/IN2（可互换），Q 接 Y。可试接 A → Y 或把 A 接到两个门输入来查看反馈。Q 回接门输入、同一目标重复接线或多驱动会被拒绝。
3. 切换 A、B 并逐次「试运行」，表格记录四组实测值；改线清空旧试跑记录。未接线会列出具体端口；若能读到 Y，同时显示预期与实测，包括碰巧相同的错误接法。
4. 纯键盘用 Tab/Shift+Tab 导航，Enter/Space 操作；焦点有描边。Esc 先取消选中的信号源，无选中源时回起始页。退出保留本页接线和输入值，继续时重置试跑记录；刷新清空。

## 接入边界

`static/js/nand-preview-runner.js` 提供 `window.HuaxiaNandPreviewRunner`，同步 `mount(element, {instanceId, config, draft, signal}, callbacks)`，配置为 `{inputs: 2, allowedGates: ["NAND"], target: "NAND"}`。实际预览使用 `HuaxiaSceneHost.beginTask`，实例 ID 为 `nand-preview-fixture-<序号>`。退出走现有 `returnToScene` / `finishReturn`，读取和恢复用本页 fixture，未调用正式场景或进度服务。

草稿示例（本预览格式 v1，未冻结成正式答案 schema）：

```json
{
  "version": 1,
  "inputs": {"A": 0, "B": 1},
  "wires": [
    {"from": "A", "to": "IN1"},
    {"from": "B", "to": "IN2"},
    {"from": "Q", "to": "Y"}
  ]
}
```

- `exportDraft()` 同步返回独立 JSON 快照；暂停后仍可导出，卸载后拒绝。草稿不含选线状态、试跑记录、成绩、身份或永久状态。
- 无草稿时从空白开始；非法草稿在挂载前拒绝。可恢复部分接线和可演算的错误接法；未知端口、反馈回路、重复线、同一目标多驱动、非法版本和值被拒绝。
- `pause()` 禁用操作；同一容器有效重复挂载先卸载旧实例。 `dispose()` 可重复，移除该实例 DOM、按键和中止监听；外部 `signal` 中止也卸载。旧控件不会触发新实例回调。
- 回调只用 `draftChanged(draft)`、`operationCompleted({draft})`、`exitRequested({draft})`。四组均实跑且接线正确才触发一次本地 `operationCompleted`；改线后重新验证。未实现提交按钮或正式判题。SceneHost 仍按 v1 附 `instanceId`、`generation`，无公共契约变更。
- `static/js/nand-preview.js` 将草稿留在页面内存，切出后按 SceneHost 生命周期卸载；可在起始页继续或清空。不使用 `localStorage`、`sessionStorage`、API 或账号。

## 实测证据

`node --check static/js/nand-preview-runner.js`、`node --check static/js/nand-preview.js`、`node --check scripts/nand-preview.test.cjs` 通过。 `node --test scripts/nand-preview.test.cjs` 8 项通过，覆盖四组正确及错误值、错误反馈、非法草稿、JSON 往返、暂停、重复挂载/卸载和旧回调、Esc 和输入隔离、实际 SceneHost 退出/恢复。 `npm run test:ui` 89 项通过，原脚本未修改。

内置浏览器用真实键盘 Tab、Shift+Tab、Enter、Space、Esc 从起始页完成接线、错误试跑、拆线、取消、修正、正确试跑、退出及继续。退出后焦点回「继续接线」，继续后回 A；3 条线恢复、试跑记录清空。另用鼠标拆线、接错、修正和逐组试跑。正确输出为 1/1/1/0；A 直连 Y 时实测 0/0/1/1，输入 10 尽管输出碰巧一致仍报 Y 接错。

| 视口 | 正确 | 错误 | 页面滚动尺寸 |
|---|---|---|---|
| 1366×768 | [实拍](images/nand-preview-1366-correct.jpg) | [实拍](images/nand-preview-1366-error.jpg) | 1366×768 |
| 1920×1080 | [实拍](images/nand-preview-1920-correct.jpg) | [实拍](images/nand-preview-1920-error.jpg) | 1920×1080 |

两尺寸的正误态无页面滚动。起始页亦在 1366×768 和 1920×1080（退出后）量测无溢出。复查了 SVG 与按钮锚点，修正 Q 按钮遮住反相标志的问题，四图均为修正后的实际页面。最终内置浏览器恢复默认 1280×720，正确态无滚动，无警告或错误日志。未使用原生 Edge。

仅单个固定 NAND 门；没有自由摆放、拖拽或正式题库。未运行 Django/PostgreSQL、真实账号、云存档、服务端核验和跨浏览器测试，待正式运行器与 B 评审接轨时处理。未推送、未部署。
