/* 任务栏组件（B 的接口，A 的大地图用同一份）。
 *
 * 为什么要抽出来：玩家真正提交判分的页面是 /game/level/<id>（电路工坊的「结算工数」），
 * 而任务栏原来长在 /game/ 的卡片里——反馈和提交永远不在同一屏。现在它不认识任何
 * 具体页面：页面只提供一个空挂载点，组件自己去读同一份进度。
 *
 * 对外只有两个入口：
 *   window.HuaxiaQuestBar.mountQuestBar(el, chapterId)   → 句柄（el 是挂载点元素）
 *   window.HuaxiaQuestBar.refresh()                     → 重新读取所有挂载点
 * el 的 data-variant="compact" 时渲染精简版（只有标题 + 状态），默认 "full"。
 *
 * 数据来源（沿用现状，不新造接口）：
 *   文案  —— 模板里的 {{ quest|json_script:"quest-meta" }}，服务端下发，前端不写死
 *   进度  —— /game/api/chapters/<chapterId>/progress，经 chapter-sdk 读取
 *
 * 页面 → 组件的三种通知（document 上派发，detail.chapterId 可选；不带就通知所有挂载点）：
 *   huaxia:quest-progress  detail:{progress}  页面已读到存档，直接渲染，省一次请求
 *   huaxia:quest-pending   detail:{pending}   提交进行中 → 「核验中」
 *   huaxia:quest-changed                      进度变了但没带数据 → 组件自己重读
 *
 * 三条硬约束：
 * 1. 不写 localStorage / sessionStorage：SDK 的测试要求页面不留持久状态。
 * 2. 每一步的勾选状态都从存档推导，不另存一份进度，否则两处状态迟早对不上。
 * 3. 本章存档没有对应字段时（例如电路章节根本没有 story / practice），
 *    这一步标为 unknown 并淡化显示，而不是猜一个勾——宁可少说，也不要骗玩家。
 */
"use strict";
(() => {
  const instances = [];
  let seq = 0;

  // ---------- 读数据 ----------
  function questMeta() {
    const holder = document.getElementById("quest-meta");
    if (!holder) return null;
    try {
      const parsed = JSON.parse(holder.textContent || "null");
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch { return null; }
  }

  function storyOf(progress) {
    const state = progress && progress.state;
    return (state && state.story) || null;
  }

  function answersOf(progress) {
    const practice = progress && progress.state && progress.state.practice;
    const answers = practice && practice.answers;
    return Array.isArray(answers) ? answers : null;
  }

  /** 最近一次尝试。两类章节都记在 attempts 里，形状一致。 */
  function lastAttemptOf(progress) {
    const state = (progress && progress.state) || {};
    const story = state.story;
    const circuit = state.circuit;
    const list = (story && Array.isArray(story.attempts) && story.attempts.length ? story.attempts : null)
      || (circuit && Array.isArray(circuit.attempts) ? circuit.attempts : null);
    return list && list.length ? list[list.length - 1] : null;
  }

  /** 任务状态。
   *
   * 章节存档里有 story.quest 就用它（sample-counting 这类）。
   * 没有的话（电路章节）按它自己的 circuit 字段推断：
   * 已结算 → submitted；刚通过等结算 → ready；上次没过 → failed；其余 → in_progress。
   */
  function npcStateOf(progress, npcId) {
    const state = (progress && progress.state) || {};
    const npcs = state.npcs;
    if (!npcs || !npcId) return null;
    return npcs[npcId] || null;
  }

  function questStateOf(progress, npcId) {
    const story = storyOf(progress);
    if (story && typeof story.quest === "string") return story.quest;
    // 多 NPC 章节：每个 NPC 一份状态，挂载点用 data-npc 声明自己是哪一个。
    const npc = npcStateOf(progress, npcId);
    if (npc && typeof npc.quest === "string") return npc.quest;
    if (!progress) return null;
    if (progress.result) return "submitted";
    const circuit = progress.state && progress.state.circuit;
    if (circuit) {
      if (circuit.pendingSettle) return "ready";
      const last = lastAttemptOf(progress);
      return last && !last.passed ? "failed" : "in_progress";
    }
    return "accepted";
  }

  /** 单步状态。done 取 true / false / "unknown"（本节存档看不出这一项）。 */
  function stepState(kind, progress, npcId) {
    const story = storyOf(progress);
    const npc = npcStateOf(progress, npcId);
    const answers = answersOf(progress);
    const result = (progress && progress.result) || null;
    if (kind === "talk") {
      if (story && "talkedToNpc" in story) return { done: Boolean(story.talkedToNpc) };
      if (npc && "talkedToNpc" in npc) return { done: Boolean(npc.talkedToNpc) };
      return { done: "unknown", why: "本章存档不记录对话进度" };
    }
    if (kind === "answers") {
      if (!answers) {
        const circuit = progress?.state?.circuit;
        if (Array.isArray(circuit?.puzzleIds) && circuit.puzzleIds.length) {
          return {done: circuit.puzzleIds.every(id => circuit.levels?.[id]?.passed === true)};
        }
        return result ? { done: true } : { done: "unknown", why: "本章存档不记录答题进度" };
      }
      const filled = answers.filter(value => value !== null && value !== undefined).length;
      return { done: answers.length > 0 && filled === answers.length, note: `${filled}/${answers.length}` };
    }
    if (kind === "submit") return { done: Boolean(result) };
    return { done: "unknown", why: `未知的步骤类型 ${kind}` };
  }

  // ---------- 建 DOM ----------
  function build(handle) {
    const make = (tag, className, part) => {
      const el = document.createElement(tag);
      el.className = className;
      if (part) el.dataset.questPart = part;
      return el;
    };

    const root = make("div", "quest-bar");
    root.dataset.variant = handle.variant;
    root.dataset.chapter = handle.chapterId;

    const head = make("div", "quest-bar-head");
    const route = make("span", "quest-bar-route", "route");
    route.hidden = true;
    const title = make("h3", "quest-bar-title", "title");
    // 状态变化要能被读屏读到：提交结果落在这里。
    const state = make("span", "quest-bar-state", "state");
    state.setAttribute("role", "status");

    const toggle = make("button", "secondary quest-bar-toggle", "toggle");
    toggle.type = "button";
    toggle.textContent = "收起 ▴";
    toggle.setAttribute("aria-expanded", "true");

    const body = make("div", "quest-bar-body", "body");
    const objective = make("p", "quest-bar-objective", "objective");
    const steps = make("ol", "quest-bar-steps", "steps");
    body.append(objective, steps);

    // id 只用于 aria-controls，带实例前缀，避免多挂载点或宿主页面自带同名 id。
    body.id = `${handle.key}-body`;
    state.id = `${handle.key}-state`;
    toggle.setAttribute("aria-controls", body.id);

    head.append(route, title, state, toggle);
    root.append(head, body);
    return { root, route, title, state, toggle, body, objective, steps };
  }

  // ---------- 渲染 ----------
  function renderState(handle, quest) {
    const pill = handle.parts.state;
    const result = (handle.progress && handle.progress.result) || null;
    if (handle.pending) {
      // 提交已经发出但还不知道结果：既不说成功也不说失败。
      pill.textContent = "核验中…";
      delete pill.dataset.tone;
      return;
    }
    if (result) {
      if (result.score == null) {
        // 非计分章节（chapter.grade = None）：有提交时间但没有分数。
        // 这里绝不能走"满分算通过"的判断——null === null 会得到 true，
        // 界面就会显示「已通过 · null / null」，看起来像系统坏了。
        pill.textContent = "已提交 · 不计分";
        delete pill.dataset.tone;
        return;
      }
      // 一次结算语义：满分算通过，差几分也照实显示，不粉饰。
      const passed = result.score === result.maxScore;
      pill.textContent = `${passed ? "已通过" : "未通过"} · ${result.score} / ${result.maxScore}`;
      pill.dataset.tone = passed ? "pass" : "fail";
      return;
    }
    if (quest === "failed") {
      // 失败的尝试不入库，所以照实说"没通过 + 还能再试"，而不是假装结束。
      const last = lastAttemptOf(handle.progress);
      pill.textContent = last
        ? `未通过 · ${last.score} / ${last.maxScore}（可再试）`
        : "未通过（可再试）";
      pill.dataset.tone = "fail";
      return;
    }
    if (quest === "awaiting_delivery") {
      pill.textContent = "待交付";
      delete pill.dataset.tone;
      return;
    }
    if (quest === "ready") {
      pill.textContent = "待结算";
      delete pill.dataset.tone;
      return;
    }
    pill.textContent = "进行中";
    delete pill.dataset.tone;
  }

  function renderSteps(handle, meta) {
    const list = handle.parts.steps;
    list.replaceChildren();
    for (const step of meta.steps || []) {
      const info = stepState(step.kind, handle.progress, handle.npcId);
      const item = document.createElement("li");
      item.textContent = info.note ? `${step.text}（${info.note}）` : (step.text || "");
      item.dataset.kind = step.kind || "";
      item.dataset.done = info.done === "unknown" ? "unknown" : String(Boolean(info.done));
      if (info.why) item.title = info.why;
      list.appendChild(item);
    }
  }

  function applyCollapse(handle) {
    const { body, toggle } = handle.parts;
    if (handle.variant === "compact") { body.hidden = true; toggle.hidden = true; return; }
    body.hidden = handle.collapsed;
    toggle.hidden = false;
    toggle.setAttribute("aria-expanded", String(!handle.collapsed));
    toggle.textContent = handle.collapsed ? "展开 ▾" : "收起 ▴";
  }

  function render(handle) {
    const meta = questMeta();
    const quest = questStateOf(handle.progress, handle.npcId);
    // 未接任务时整条栏不出现；没有文案数据时也不画半个空栏。
    if (!meta || quest === null || quest === "not_started") {
      handle.el.hidden = true;
      delete handle.el.dataset.questState;
      return;
    }
    handle.el.hidden = false;
    handle.el.dataset.questState = quest;

    handle.parts.title.textContent = meta.title || "";
    handle.parts.objective.textContent = meta.objective || "";
    handle.parts.route.hidden = !meta.route;
    if (meta.route) handle.parts.route.textContent = meta.route === "side" ? "支线" : "主线";

    renderState(handle, quest);
    renderSteps(handle, meta);
    applyCollapse(handle);
  }

  // ---------- 读取进度 ----------
  async function load(handle) {
    if (!window.HuaxiaChapterClient) return;
    const version = ++handle.progressVersion;
    try {
      if (!handle.client) handle.client = new window.HuaxiaChapterClient(handle.chapterId);
      const data = await handle.client.load();
      if (version === handle.progressVersion) handle.render(data.progress);
    } catch {
      // 读不到存档（未登录、网络、章节不存在）时不画半个任务栏，也不把异常抛给页面。
      if (version === handle.progressVersion) handle.el.hidden = true;
    }
  }

  // ---------- 对外接口 ----------
  function mountQuestBar(el, chapterId) {
    if (!el || typeof chapterId !== "string" || !chapterId) return null;
    const mounted = instances.find(item => item.el === el);
    if (mounted) return mounted;          // 同一挂载点重复调用时复用，不叠两层

    seq += 1;
    const handle = {
      el,
      chapterId,
      key: `quest-bar-${seq}`,
      variant: el.dataset.variant === "compact" ? "compact" : "full",
      // 多 NPC 章节靠挂载点上的 data-npc 指明"这个任务栏属于谁"。
      npcId: el.dataset.npc || "",
      collapsed: false,
      pending: false,
      progress: null,
      progressVersion: 0,
      client: null,
      parts: null,
    };
    handle.parts = build(handle);
    el.replaceChildren(handle.parts.root);
    el.hidden = true;

    handle.parts.toggle.addEventListener("click", () => {
      handle.collapsed = !handle.collapsed;
      applyCollapse(handle);
    });
    handle.refresh = () => load(handle);
    handle.setPending = pending => { handle.pending = Boolean(pending); render(handle); };
    // 页面自己已经读到存档时用它，省掉一次对 /progress 的往返。
    handle.render = progress => {
      if (progress) { handle.progress = progress; handle.progressVersion++; }
      render(handle);
    };
    handle.destroy = () => {
      handle.progressVersion++;
      const at = instances.indexOf(handle);
      if (at >= 0) instances.splice(at, 1);
      el.replaceChildren();
      el.hidden = true;
    };

    instances.push(handle);
    render(handle);          // 先按现有状态画一次，页面随后可以推更准的存档
    void load(handle);
    return handle;
  }

  function refresh() {
    return Promise.all(instances.map(handle => load(handle)));
  }

  /** 事件要作用在哪些挂载点上：带了 chapterId 就只给同章节的。 */
  function targeted(event) {
    const detail = event.detail || {};
    const chapterId = detail.chapterId || (detail.progress && detail.progress.chapterId);
    if (!chapterId) return instances.slice();
    return instances.filter(handle => handle.chapterId === chapterId);
  }

  document.addEventListener("huaxia:quest-progress", event => {
    const progress = event.detail && event.detail.progress;
    if (!progress) return;
    for (const handle of targeted(event)) handle.render(progress);
  });

  document.addEventListener("huaxia:quest-pending", event => {
    const pending = Boolean(event.detail && event.detail.pending);
    for (const handle of targeted(event)) handle.setPending(pending);
  });

  document.addEventListener("huaxia:quest-changed", event => {
    for (const handle of targeted(event)) void load(handle);
  });

  window.HuaxiaQuestBar = { mountQuestBar, refresh };
})();
