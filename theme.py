#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 主题配置助手 —— 对标 CodeWhale 的 /theme

用法：
  python3 ~/.claude/theme.py                  # 列出当前主题与可选主题
  python3 ~/.claude/theme.py --set dark       # 切换主题（写入前自动备份）
  python3 ~/.claude/theme.py --revert         # 从最近一次本工具备份恢复 theme
  python3 ~/.claude/theme.py --json           # 机器可读输出
  python3 ~/.claude/theme.py --settings <路径> # 指定配置文件（测试用，默认 ~/.claude.json）

已在本机 Claude Code v2.1.258 二进制中核实的事实：
  · 内置主题 id（共 6 个）：dark / light / dark-ansi / light-ansi /
    dark-daltonized / light-daltonized
    实证来源：`RRn=["dark","light","light-daltonized","dark-daltonized","light-ansi","dark-ansi"]`
  · **写入位置 = `~/.claude.json`（globalConfig）的顶层 `theme`，不是 settings.json！**
    实证来源（v2.1.258，store 初始化）：`themeSetting: i.theme` 取自 globalConfig，
    而 `currentLanguage: e?.language` 才取自 settingsData。settings.json 的 zod schema 里
    **确实**定义了 theme 字段，但它不在 TUI 主题 store 的读取路径上 —— **schema 存在 ≠ 生效**。
  · **取值 = `custom:<slug>`**（slug 即主题文件名去掉 .json）。实证来源：
      function k9(e){return `${k}${e}`}                     // k = "custom:"
      function aT(e){return e.startsWith(k)?e.slice(k.length):null}
      theme: We([ee(cCt), i().startsWith("custom:").transform(r=>r)]).optional().catch(void 0)
      {let{value:I}=d("theme","dark"); if(I.startsWith("custom:")) import(...).then(...)}
  · **写入不带 `custom:` 前缀的名字（如 "Dracula"）会静默回退成 `dark`**，而不是保持原主题。
    实证来源：function p4e(e){ if(e==="auto")return Bz(); if(Hbt(e))return e;
                              let t=aT(e); return t&&Yln(t)||"dark" }
    其中 Hbt() 只认 6 个内置 id，aT() 只认 `custom:` 前缀 —— 两者都不中即落到最后的 "dark"。
  · 自定义主题目录：~/.claude/themes/*.json，字段形如
    {"name": "Catppuccin Mocha", "base": "dark", "overrides": {...}}
    加载器实证：function j(e,r,s){ ... let h=Hbt(a.base)?a.base:"dark", f=typeof a.name==="string"?a.name:e ... }
    —— base 必须是内置 id，否则按 "dark" 处理；name 缺省时用文件名兜底。
"""

import argparse
import json
import os
import shutil
import sys
from datetime import datetime

HOME = os.path.expanduser("~")
# ★ 主题存在 globalConfig（~/.claude.json）里，不在 settings.json 里。
# 详见 ~/.claude/projects/-Users-ootd/memory/claude-code-theme-mechanism.md
DEFAULT_SETTINGS = os.path.join(HOME, ".claude.json")
THEMES_DIR = os.path.join(HOME, ".claude", "themes")
BACKUP_PREFIX = "claude.json.bak-theme-"

# 已实证的内置主题 id（顺序即设置面板里的呈现顺序：深色 / 浅色 / 深色 ANSI / 浅色 ANSI / 色盲友好）
BUILTIN_THEMES = [
    ("dark", "深色（默认）"),
    ("light", "浅色"),
    ("dark-ansi", "深色 ANSI（仅用 16 色，终端配色跟随）"),
    ("light-ansi", "浅色 ANSI"),
    ("dark-daltonized", "深色 · 色盲友好"),
    ("light-daltonized", "浅色 · 色盲友好"),
]

# 自定义主题在 settings.json 中的取值前缀（二进制里为变量 k，值实测为 "custom:"）
CUSTOM_PREFIX = "custom:"

DIM = "\033[2m"
BOLD = "\033[1m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"


# ---------- 输出小工具 ----------

class Paint:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def __call__(self, text, color=""):
        if not self.enabled or not color:
            return text
        return f"{color}{text}{RESET}"


def is_tty():
    return sys.stdout.isatty()


# ---------- settings.json 读写 ----------

def load_settings(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def detect_indent(raw):
    """按原文件的缩进风格写回，避免整文件重排。"""
    for line in raw.splitlines():
        stripped = line.lstrip(" ")
        if stripped and line != stripped:
            return len(line) - len(stripped)
    return 2


def backup_settings(path):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = os.path.join(os.path.dirname(path), f"{BACKUP_PREFIX}{ts}")
    shutil.copy2(path, backup)
    return backup


def write_settings(path, data, indent):
    """原子写 + 写后回读校验；失败则抛异常（调用方负责从备份恢复）。"""
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)
    with open(path, encoding="utf-8") as fh:
        check = json.load(fh)
    if check != data:
        raise RuntimeError("写后回读校验失败，文件内容与预期不一致")


def latest_backup(path):
    directory = os.path.dirname(path) or "."
    candidates = sorted(
        (name for name in os.listdir(directory) if name.startswith(BACKUP_PREFIX))
    )
    return os.path.join(directory, candidates[-1]) if candidates else None


# ---------- 自定义主题 ----------

def load_custom_themes():
    """返回 [(name, slug, base, path)]，按 name 排序；解析失败的主题跳过。"""
    themes = []
    if not os.path.isdir(THEMES_DIR):
        return themes
    for name in sorted(os.listdir(THEMES_DIR)):
        if not name.endswith(".json"):
            continue
        full = os.path.join(THEMES_DIR, name)
        slug = name[: -len(".json")]
        try:
            with open(full, encoding="utf-8") as fh:
                data = json.load(fh)
            themes.append((data.get("name") or slug, slug, data.get("base", "?"), full))
        except Exception:
            continue
    themes.sort(key=lambda item: item[0].lower())
    return themes


def resolve_target(value, custom):
    """把用户输入解析成写入值。返回 (写入值, 类型, 提示)。

    类型：builtin / custom / unknown

    自定义主题接受 name（"Dracula"）、slug（"dracula"）或带前缀的
    "custom:dracula" 三种写法，但**一律归一化成 `custom:<slug>` 再写入**——
    直接写名字会被 TUI 的 p4e() 静默回退成 dark。
    """
    if value in [tid for tid, _ in BUILTIN_THEMES]:
        return value, "builtin", None
    raw = value[len(CUSTOM_PREFIX):] if value.startswith(CUSTOM_PREFIX) else value
    for name, slug, _base, _path in custom:
        if raw in (name, slug):
            hint = f"自定义主题「{name}」→ 写入 `{CUSTOM_PREFIX}{slug}`（base={_base}）"
            return f"{CUSTOM_PREFIX}{slug}", "custom", hint
    return None, "unknown", None


# ---------- 子命令 ----------

def cmd_list(settings_path, as_json, paint):
    settings = load_settings(settings_path)
    current = settings.get("theme")
    custom = load_custom_themes()
    builtin_ids = [tid for tid, _ in BUILTIN_THEMES]

    if as_json:
        print(
            json.dumps(
                {
                    "settings_path": settings_path,
                    "current": current,
                    "builtin": [{"id": tid, "label": label} for tid, label in BUILTIN_THEMES],
                    "custom": [
                        {
                            "name": name,
                            "slug": slug,
                            "base": base,
                            "path": path,
                            "settings_value": f"{CUSTOM_PREFIX}{slug}",
                        }
                        for name, slug, base, path in custom
                    ],
                    "available": current in builtin_ids
                    or current in [f"{CUSTOM_PREFIX}{s}" for _n, s, _b, _p in custom],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    by_value = {f"{CUSTOM_PREFIX}{slug}": name for name, slug, _b, _p in custom}
    current_label = current or "(未设置)"
    if current in by_value:
        current_label = f"{current}（{by_value[current]}）"
    print(f"{paint('当前主题', BOLD)}  {paint(current_label, CYAN)}")
    print(f"{paint('配置文件', DIM)}  {settings_path}")
    print()
    print(paint("内置主题", BOLD))
    for tid, label in BUILTIN_THEMES:
        mark = paint("●", GREEN) if tid == current else " "
        print(f"  {mark} {tid:<18}{paint(label, DIM)}")
    print()
    print(paint(f"自定义主题（{THEMES_DIR}）", BOLD))
    if not custom:
        print(f"  {paint('（无）', DIM)}")
    else:
        for name, slug, base, _path in custom:
            value = f"{CUSTOM_PREFIX}{slug}"
            mark = paint("●", GREEN) if value == current else " "
            print(f"  {mark} {name:<18}{paint(f'{value} · base={base}', DIM)}")
        print()
        print(
            paint(
                "  说明：写入值为 `custom:<文件名>`。直接写主题名（如 Dracula）会被 TUI "
                "静默回退成 dark —— 已在 v2.1.258 二进制中实证。",
                DIM,
            )
        )
    return 0


def cmd_set(settings_path, value, as_json, paint, dry_run=False):
    settings = load_settings(settings_path)
    custom = load_custom_themes()
    resolved, kind, hint = resolve_target(value, custom)

    if resolved is None:
        options = ", ".join([tid for tid, _ in BUILTIN_THEMES])
        print(f"{paint('未知主题', RED)}：{value}", file=sys.stderr)
        print(f"可选内置主题：{options}", file=sys.stderr)
        if custom:
            print(
                "可选自定义主题：" + ", ".join(name for name, _s, _b, _p in custom),
                file=sys.stderr,
            )
        return 2

    old = settings.get("theme")
    if old == resolved:
        print(f"当前已经是 {paint(resolved, CYAN)}，未做改动。")
        return 0

    with open(settings_path, encoding="utf-8") as fh:
        indent = detect_indent(fh.read())

    if as_json:
        print(
            json.dumps(
                {
                    "settings_path": settings_path,
                    "changes": {"theme": {"old": old, "new": resolved}},
                    "kind": kind,
                    "dry_run": dry_run,
                    "hint": hint,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"将把 {paint('theme', BOLD)}：{old!r} → {paint(repr(resolved), CYAN)}")
    if hint:
        print(paint(f"提示：{hint}", YELLOW))
    if dry_run:
        print(paint("（--dry-run：未写入）", DIM))
        return 0

    backup = backup_settings(settings_path)
    settings["theme"] = resolved
    try:
        write_settings(settings_path, settings, indent)
    except Exception as exc:  # 写失败立刻从备份还原
        shutil.copy2(backup, settings_path)
        print(f"{paint('写入失败，已从备份还原', RED)}：{exc}", file=sys.stderr)
        return 1

    print(f"{paint('已切换', GREEN)}：{resolved}")
    print(f"{paint('备份', DIM)}：{backup}")
    print(paint("重启 claude 会话后生效（TUI 内也可用 /theme 即时切换）。", DIM))
    print(
        paint(
            "⚠️ ~/.claude.json 由 CLI 常驻进程持有，正在运行的会话退出时可能把它覆写回去；"
            "改完请在 TUI 里确认，或直接用 TUI 的 /theme 切换。",
            YELLOW,
        )
    )
    return 0


def cmd_revert(settings_path, as_json, paint):
    backup = latest_backup(settings_path)
    if backup is None:
        print(f"{paint('没有找到本工具的备份', RED)}：{BACKUP_PREFIX}*", file=sys.stderr)
        return 2

    settings = load_settings(settings_path)
    try:
        with open(backup, encoding="utf-8") as fh:
            saved = json.load(fh)
    except Exception as exc:
        print(f"{paint('备份读取失败', RED)}：{exc}", file=sys.stderr)
        return 1

    target = saved.get("theme")
    with open(settings_path, encoding="utf-8") as fh:
        indent = detect_indent(fh.read())

    if as_json:
        print(
            json.dumps(
                {
                    "settings_path": settings_path,
                    "backup": backup,
                    "changes": {"theme": {"old": settings.get("theme"), "new": target}},
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    old = settings.get("theme")
    settings["theme"] = target
    try:
        write_settings(settings_path, settings, indent)
    except Exception as exc:
        print(f"{paint('回退写入失败', RED)}：{exc}", file=sys.stderr)
        return 1

    print(f"已从 {paint(os.path.basename(backup), DIM)} 回退：{old!r} → {paint(repr(target), CYAN)}")
    return 0


# ---------- 入口 ----------

def main():
    parser = argparse.ArgumentParser(
        description="Claude Code 主题配置助手（对标 CodeWhale /theme）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--set", metavar="主题", help="切换主题（内置 id 或自定义主题 name）")
    parser.add_argument("--revert", action="store_true", help="从最近一次备份恢复 theme")
    parser.add_argument("--dry-run", action="store_true", help="只展示改动，不写盘")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    parser.add_argument(
        "--settings",
        "--config",
        dest="settings",
        default=DEFAULT_SETTINGS,
        help="配置文件路径（默认 ~/.claude.json；主题存在这里，不在 settings.json）",
    )
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    args = parser.parse_args()

    paint = Paint(enabled=not args.no_color and is_tty())

    if not os.path.isfile(args.settings):
        print(f"{paint('找不到配置文件', RED)}：{args.settings}", file=sys.stderr)
        return 2

    try:
        if args.revert:
            return cmd_revert(args.settings, args.json, paint)
        if args.set:
            return cmd_set(args.settings, args.set, args.json, paint, args.dry_run)
        return cmd_list(args.settings, args.json, paint)
    except json.JSONDecodeError as exc:
        print(f"{paint('配置文件不是合法 JSON', RED)}：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
