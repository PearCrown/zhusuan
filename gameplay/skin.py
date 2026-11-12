"""界面皮肤：主题、布局、界面文案。

这个平台将来可能做成剧情游戏，也可能做成大地图 RPG，风格会反复推翻重做。
所以「长什么样」必须和「怎么运作」分开。这里把三样东西抽出来：

  theme   一套 CSS 变量，放在 static/css/themes/<name>.css
  layout  一套布局规则，写在 static/css/circuits.css 的 [data-layout="..."] 段
  文案    一份 JSON，按钮叫「呈上验符」还是「提交」，改这里

换风格只需要改 settings 里两个字符串（或用环境变量 GAME_THEME / GAME_LAYOUT）。
新增风格不需要写 Python：放一个 CSS 文件，或加一段 [data-layout] 即可。

出错时的策略是「降级而不崩」：主题名打错就退回默认主题，并把原因记进
warnings——因为这是开发期最常见的笔误，不值得让整个页面打不开。
"""

import json
from pathlib import Path

from django.conf import settings

DEFAULT_THEME = "bronze-forge"
DEFAULT_LAYOUT = "forge"

# 已实现的布局。新增布局时在 circuit.css 里加 [data-layout="新名字"] 段，
# 再把这个名字登记进来，这样拼错时会被发现而不是静默生效。
LAYOUTS = ("forge", "stage")

THEME_DIR = Path(settings.BASE_DIR) / "static" / "css" / "themes"
UI_STRINGS_PATH = Path(__file__).resolve().parent / "data" / "ui_strings.json"

REQUIRED_KEYS = (
    "brandSeal", "homeLink", "paletteTitle", "paletteHint", "actionsTitle",
    "actionClear", "actionSim", "actionStop", "actionSubmit", "actionSettle",
    "progressTitle", "legendTitle", "legendOne", "legendZero", "legendHint",
    "questTitle", "truthTitle", "simTitle", "simPrev", "simNext",
    "truthYaoHeader", "resultTitle", "continue", "canvasLabel", "readingSave",
)

_ui_cache = None


class SkinError(ValueError):
    """配置错误（开发期问题，不是用户输入问题）。"""


def available_themes():
    if not THEME_DIR.is_dir():
        return ()
    return tuple(sorted(path.stem for path in THEME_DIR.glob("*.css")))


def _load_uncached(path=None):
    """读取并校验文案。path 可指定，便于测试与将来做实时预览。"""
    raw = (path or UI_STRINGS_PATH).read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise SkinError(f"界面文案不是合法 JSON：{exc}") from exc
    missing = [key for key in REQUIRED_KEYS
               if not isinstance(parsed.get(key), str) or not parsed[key].strip()]
    if missing:
        raise SkinError(f"界面文案缺少字段：{'、'.join(missing)}")
    return parsed


def load_ui_strings():
    """带缓存的读取：进程内只解析一次。"""
    global _ui_cache
    if _ui_cache is None:
        _ui_cache = _load_uncached()
    return _ui_cache


def resolve_skin(theme=None, layout=None):
    """解析当前皮肤，返回模板直接可用的上下文。

    theme/layout 显式传入时优先，方便测试和将来做「预览另一套风格」。
    """
    warnings = []

    requested_theme = (theme or getattr(settings, "GAME_THEME", DEFAULT_THEME) or "").strip()
    if requested_theme not in available_themes():
        warnings.append(f"未找到主题 {requested_theme!r}，已回退到 {DEFAULT_THEME}")
        requested_theme = DEFAULT_THEME if DEFAULT_THEME in available_themes() else ""
    if not requested_theme:
        warnings.append("themes/ 目录里没有任何主题文件，页面将缺少配色变量")

    requested_layout = (layout or getattr(settings, "GAME_LAYOUT", DEFAULT_LAYOUT) or "").strip()
    if requested_layout not in LAYOUTS:
        warnings.append(f"未知布局 {requested_layout!r}，已回退到 {DEFAULT_LAYOUT}")
        requested_layout = DEFAULT_LAYOUT

    return {
        "theme": requested_theme,
        "layout": requested_layout,
        "theme_href": f"css/themes/{requested_theme}.css" if requested_theme else "",
        "ui": load_ui_strings(),
        "warnings": warnings,
        "available_themes": available_themes(),
        "available_layouts": LAYOUTS,
    }
