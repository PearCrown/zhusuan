"""奖励账本：以 rewardId 为键，记录发放时间与次数。

为什么把账本放进章节 state，而不是新建一张表：

- 奖励归属章节进度，和存档同生共死。新表要额外付三份维护成本：迁移、
  级联删除，以及第四处需要同样过滤口径的查询。
- 并发不需要任何新机制。发放只发生在 `services.apply_action` 内，而它已经是
  `@transaction.atomic` + `User.objects.select_for_update()`，同一账号的修改被串行化；
  账本与成绩在同一个事务里落盘，不存在「奖励发了但存档没存」。
- 老存档零成本。没有 rewards 键时就地补一张空表，不升 schema_version
  （升版会让 get_progress 对老存档返回 409，等于卡死玩家）。

为什么不直接用 set / 布尔：
将来支线奖励可能要「可重复领取 N 次」或「每日一次」，时间戳 + 次数是这两种
需求的最小公共结构。limit 默认 1，就是现在「只发一次」的语义。

不变式（有测试守护）：
1. 同一 rewardId 的 firstAt 一旦写入就不再被覆盖——它是「只发过一次」的证据。
2. 发放被拒时不改 count、不改 lastAt，只写 lastAttemptAt 留痕。
"""

LIMIT_DEFAULT = 1


def ledger(state):
    """拿到（必要时补建）账本本身。老存档没有 rewards 键时补一张空表。"""
    return state.setdefault("rewards", {})


def entry_of(state, reward_id):
    """账本里的某一条；从未发过时返回 None。"""
    return ledger(state).get(reward_id)


def granted(state, reward_id):
    """这个奖励是否已经发满。"""
    entry = entry_of(state, reward_id)
    if not entry:
        return False
    return entry.get("count", 0) >= entry.get("limit", LIMIT_DEFAULT)


def grant(state, reward_id, *, at, limit=LIMIT_DEFAULT):
    """尝试发放一次。

    返回 True 表示这次真的发了；返回 False 表示已达上限，只留下
    lastAttemptAt 作为「有人又领过一次但没发」的痕迹。

    发放前查账本 —— 这就是「重玩不能刷奖励」的全部机制，没有第二处判断。
    """
    if not isinstance(reward_id, str) or not reward_id:
        raise ValueError("reward id 必须是非空字符串")
    if not isinstance(at, str) or not at:
        raise ValueError("reward 发放时间必须是非空字符串")

    book = ledger(state)
    entry = book.get(reward_id)
    if entry is None:
        book[reward_id] = {"count": 1, "limit": limit, "firstAt": at, "lastAt": at}
        return True
    if entry.get("count", 0) >= entry.get("limit", LIMIT_DEFAULT):
        # 已发满：不覆盖 firstAt、不动 count，只记下这次被拒的时间。
        entry["lastAttemptAt"] = at
        return False
    entry["count"] = entry.get("count", 0) + 1
    entry["lastAt"] = at
    return True
