#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 状态栏 (statusLine) —— 参考 CodeWhale 的 /statusline 芯片布局

显示：完成成本 │ 轮次 │ LLM耗时 · 工具耗时 │ 缓存命中率 │ 输入token │ 模型

数据来源：
  · 成本/时长 —— statusLine 从 stdin 传入的 JSON
  · 轮次/token/缓存/工具耗时 —— 增量解析 transcript JSONL（按 message.id 去重）

价格：改 ~/.claude/statusline-prices.json（人民币 / 百万 token），不存在则用内置默认值。
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
CACHE_DIR = os.path.join(HOME, ".claude", ".statusline-cache")
PRICES_FILE = os.path.join(HOME, ".claude", "statusline-prices.json")

# 内置默认价（¥ / 百万 token）。务必按你实际走的渠道核对后覆盖。
# 键为模型 id 前缀，最长匹配优先。
DEFAULT_PRICES = {
    "deepseek": {"cache_hit": 0.5, "cache_miss": 2.0, "output": 8.0},
    "_default": {"cache_hit": 0.5, "cache_miss": 2.0, "output": 8.0},
}

# 汇率：仅当只能拿到美元成本时用于兜底换算
USD_CNY = 7.1

DIM = "\033[2m"
RESET = "\033[0m"
SEP = f"{DIM}│{RESET}"


# ---------- 工具函数 ----------

def fmt_dur(ms):
    if ms is None or ms <= 0:
        return "0s"
    s = ms / 1000.0
    if s < 60:
        return f"{s:.1f}s"
    m, s = divmod(int(round(s)), 60)
    if m < 60:
        return f"{m}m{s:02d}s" if s else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h{m:02d}m"


def fmt_tok(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1000:
        return f"{n / 1000:.0f}K"
    return str(n)


def parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def load_prices():
    prices = dict(DEFAULT_PRICES)
    try:
        with open(PRICES_FILE, encoding="utf-8") as fh:
            user = json.load(fh)
        if isinstance(user, dict):
            prices.update(user)
    except Exception:
        pass
    return prices


def price_for(model_id, prices):
    best, best_len = None, -1
    for key, val in prices.items():
        if key == "_default":
            continue
        if model_id and model_id.startswith(key) and len(key) > best_len:
            best, best_len = val, len(key)
    return best or prices.get("_default", DEFAULT_PRICES["_default"])


# ---------- transcript 增量解析 ----------

def new_state():
    return {
        "offset": 0,
        "turns": 0,
        "in_tok": 0,       # 未命中缓存的输入
        "cache_r": 0,      # 命中缓存读取
        "cache_c": 0,      # 缓存写入
        "out_tok": 0,
        "api_reqs": 0,
        "tool_ms": 0.0,
        "pending": {},     # tool_use_id -> 起始时间戳
        "seen_ids": [],    # 最近见过的 message.id（去重用）
    }


def ingest(rec, st):
    """把一条 transcript 记录累加进 state。"""
    rtype = rec.get("type")
    ts = parse_ts(rec.get("timestamp"))

    if rtype == "user":
        msg = rec.get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            src = rec.get("promptSource")
            if (src is None) or (src == "typed"):
                st["turns"] += 1
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "tool_result":
                    tid = blk.get("tool_use_id")
                    started = st["pending"].pop(tid, None)
                    if started and ts:
                        delta = (ts - started).total_seconds() * 1000.0
                        if 0 <= delta < 3_600_000:
                            st["tool_ms"] += delta

    elif rtype == "assistant":
        msg = rec.get("message") or {}
        mid = msg.get("id")
        seen = st["seen_ids"]
        if mid:
            if mid in seen:
                # 流式快照的重复写入：usage 已是终值，只补记可能的 tool_use
                pass
            else:
                seen.append(mid)
                if len(seen) > 800:
                    del seen[:400]
                usage = msg.get("usage") or {}
                st["in_tok"] += usage.get("input_tokens") or 0
                st["cache_r"] += usage.get("cache_read_input_tokens") or 0
                st["cache_c"] += usage.get("cache_creation_input_tokens") or 0
                st["out_tok"] += usage.get("output_tokens") or 0
                st["api_reqs"] += 1

        content = msg.get("content")
        if isinstance(content, list) and ts:
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "tool_use":
                    tid = blk.get("id")
                    if tid and tid not in st["pending"]:
                        st["pending"][tid] = ts


def analyze(tpath):
    """增量解析 transcript，返回统计字典。"""
    st = new_state()
    os.makedirs(CACHE_DIR, exist_ok=True)
    session_key = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(tpath))
    cache_file = os.path.join(CACHE_DIR, session_key + ".json")

    try:
        with open(cache_file, encoding="utf-8") as fh:
            saved = json.load(fh)
        if isinstance(saved, dict) and "offset" in saved:
            st = saved
            st["pending"] = {k: parse_ts(v) if isinstance(v, str) else None
                             for k, v in (st.get("pending") or {}).items()}
    except Exception:
        pass

    try:
        size = os.path.getsize(tpath)
    except Exception:
        size = 0

    if st.get("offset", 0) > size:      # transcript 被重写/压缩过，重来
        st = new_state()

    chunk = b""
    if size > st["offset"]:
        try:
            with open(tpath, "rb") as fh:
                fh.seek(st["offset"])
                chunk = fh.read()
        except Exception:
            chunk = b""

    if chunk:
        cut = chunk.rfind(b"\n")
        usable = chunk[: cut + 1] if cut != -1 else b""
        st["offset"] += len(usable)
        for raw in usable.split(b"\n"):
            raw = raw.strip()
            if not raw:
                continue
            try:
                ingest(json.loads(raw), st)
            except Exception:
                continue

        # 落盘（pending 里的 datetime 转回字符串）
        out = dict(st)
        out["pending"] = {k: (v.isoformat() if v else None)
                          for k, v in st["pending"].items()}
        try:
            tmp = cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(out, fh)
            os.replace(tmp, cache_file)
        except Exception:
            pass

    return st


# ---------- 主流程 ----------

def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        raw, data = "", {}

    # 留存 CC 传入的原始 JSON 与关键环境变量，便于核对（排查用，很小）
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, "last-stdin.json"), "w", encoding="utf-8") as fh:
            fh.write(raw)
        _keys = ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "ANTHROPIC_MODEL", "ANTHROPIC_BASE_URL")
        with open(os.path.join(CACHE_DIR, "last-env.json"), "w", encoding="utf-8") as fh:
            json.dump({k: os.environ.get(k) for k in _keys}, fh, ensure_ascii=False)
    except Exception:
        pass

    model = (data.get("model") or {})
    model_id = model.get("id") or ""
    model_name = (model.get("display_name") or model_id or "?").replace("[1m]", "")
    cost = data.get("cost") or {}
    tpath = data.get("transcript_path") or ""

    st = new_state()
    if tpath and os.path.exists(tpath):
        try:
            st = analyze(tpath)
        except Exception:
            pass

    # ---- 成本 ----
    prices = load_prices()
    p = price_for(model_id, prices)
    cny = (st["cache_r"] / 1e6) * p["cache_hit"] \
        + ((st["in_tok"] + st["cache_c"]) / 1e6) * p["cache_miss"] \
        + (st["out_tok"] / 1e6) * p["output"]

    # 不使用 cost.total_cost_usd：它按 Anthropic 官价计，走第三方网关必然失真
    # （实测同一会话 CC 报 $2.26，按 DeepSeek 价实际约 ¥0.8，差 20 倍）
    if cny >= 1:
        cost_str = f"¥{cny:.2f}"
    else:
        cost_str = f"¥{cny:.3f}"

    # ---- 时长 ----
    llm_ms = cost.get("total_api_duration_ms") or 0
    tool_ms = st["tool_ms"]

    # ---- 缓存命中 ----
    # 优先用 CC 官方的 prompt_cache.hit_ratio（覆盖全部请求），
    # 缺失时退回自己按 transcript 累计算的值
    total_in = st["cache_r"] + st["in_tok"] + st["cache_c"]
    hit = (st["cache_r"] / total_in * 100) if total_in else 0
    ratio = (data.get("prompt_cache") or {}).get("hit_ratio")
    if isinstance(ratio, (int, float)):
        hit = ratio * 100 if ratio <= 1 else ratio
    hit_color = "\033[32m" if hit >= 80 else ("\033[33m" if hit >= 40 else "\033[31m")

    # ---- 上下文占用 ----
    # 注意分母陷阱：CC 的 used_percentage 按模型窗口（本例 100 万）算，
    # 而 auto-compact 是按 CLAUDE_CODE_AUTO_COMPACT_WINDOW 触发的。
    # 接近阈值时二者差异致命（768K 时前者显示 77%、实际已经压缩），故优先按后者算。
    cw = data.get("context_window") or {}
    cur = cw.get("current_usage") or {}
    cur_tok = sum(cur.get(k) or 0 for k in
                  ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
    ctx_pct = None
    acw = os.environ.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW")
    if acw and cur_tok:
        try:
            ctx_pct = cur_tok / float(acw) * 100
        except Exception:
            ctx_pct = None
    if ctx_pct is None:
        up = cw.get("used_percentage")
        if isinstance(up, (int, float)):
            ctx_pct = float(up)
    ctx_str = None
    if ctx_pct is not None:
        c = "\033[31m" if ctx_pct >= 85 else ("\033[33m" if ctx_pct >= 70 else "\033[32m")
        ctx_str = f"ctx {c}{ctx_pct:.0f}%{RESET}"

    # ---- git 分支（对应 CodeWhale 的 git_branch 芯片）----
    git_str = None
    cwd = data.get("cwd") or (data.get("workspace") or {}).get("current_dir") or ""
    if cwd:
        try:
            br = subprocess.run(
                ["git", "-C", cwd, "branch", "--show-current"],
                capture_output=True, text=True, timeout=0.5,
            ).stdout.strip()
            if br:
                dirty = subprocess.run(
                    ["git", "-C", cwd, "status", "--porcelain"],
                    capture_output=True, text=True, timeout=0.5,
                ).stdout.strip()
                mark = f"\033[33m*{RESET}" if dirty else ""
                git_str = f"\033[34m⎇ {br}{RESET}{mark}"
        except Exception:
            git_str = None

    # ---- 推理强度（对应 CodeWhale 的 reasoning_replay 芯片）----
    effort = (data.get("effort") or {}).get("level") or ""
    effort_str = None
    if effort:
        label = {"high": "高", "medium": "中", "low": "低"}.get(effort.lower(), effort)
        off = (data.get("thinking") or {}).get("enabled") is False
        effort_str = f"{DIM}推理{RESET} {label}" + (f" {DIM}关{RESET}" if off else "")

    # ---- 代码增删（对应 CodeWhale 的 session_metrics 里的改动量）----
    added = cost.get("total_lines_added") or 0
    removed = cost.get("total_lines_removed") or 0
    diff_str = None
    if added or removed:
        diff_str = f"\033[32m+{added}{RESET}{DIM}/{RESET}\033[31m-{removed}{RESET}"

    # ---- 拼装（顺序向 CodeWhale 的芯片布局靠拢：
    #      cost → 轮次 → 耗时 → 改动量 → 推理 → 缓存 → git → token → ctx → model）----
    parts = [
        f"\033[36m{cost_str}{RESET}",
        f"{st['turns']}轮",
        f"\033[35mLLM {fmt_dur(llm_ms)}{RESET} {DIM}·{RESET} 工具 {fmt_dur(tool_ms)}",
    ]
    if diff_str:
        parts.append(diff_str)
    if effort_str:
        parts.append(effort_str)
    parts.append(f"缓存 {hit_color}{hit:.0f}%{RESET}")
    if git_str:
        parts.append(git_str)
    parts.append(f"输入 {fmt_tok(total_in)}")
    if ctx_str:
        parts.append(ctx_str)
    parts.append(f"{DIM}{model_name}{RESET}")

    sys.stdout.write(f" {SEP} ".join(parts))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        sys.stdout.write("")
