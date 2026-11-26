#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Claude Code 状态栏 (statusLine) —— 参考 CodeWhale 的 /statusline 芯片布局

显示：完成成本 │ 轮次 │ LLM耗时 · 工具耗时 │ 缓存命中率 │ 输入token │ 模型

数据来源：
  · 成本/时长 —— statusLine 从 stdin 传入的 JSON
  · 轮次/token/缓存/工具耗时 —— 增量解析 transcript JSONL（按 message.id 去重）

价格：改 ~/.claude/statusline-prices.json（人民币 / 百万 token，填**峰价**），
      不存在则用内置默认值；谷时段的 token 自动按 0.5 倍计价。
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
CACHE_DIR = os.path.join(HOME, ".claude", ".statusline-cache")
PRICES_FILE = os.path.join(HOME, ".claude", "statusline-prices.json")

# 内置默认价（¥ / 百万 token，**峰价**）。务必按你实际走的渠道核对后覆盖。
# 键为模型 id 前缀，最长匹配优先。
#
# ⚠️ 命中价别按官方 Anthropic 价填：走 DeepSeek 时命中价是未命中价的 1/50。
#    这里与手机端 ~/bin/网关/计价.py（已用官方账单反算核对）保持同一份口径：
#      flash 峰 0.04 / 2.0 / 8.0，谷 0.02 / 1.0 / 4.0
#      pro   峰 0.30 / 9.0 / 27.0，谷 0.15 / 4.5 / 13.5
#    DeepSeek 的谷价恰好是峰价的一半，所以只存峰价、按峰谷分桶后谷桶 ×0.5。
DEFAULT_PRICES = {
    # UI 显示名是官方 Claude 名，实际请求被 DeepSeek 映射到 deepseek-flash，
    # 所以这里必须按 flash 价计（claude-opus* 才会被映射到 v4-pro，别用）。
    "claude-sonnet-5-5": {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0},
    "deepseek-v4-pro": {"cache_hit": 0.30, "cache_miss": 9.0, "output": 27.0},
    "deepseek-v4-flash": {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0},
    "deepseek": {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0},
    "_default": {"cache_hit": 0.04, "cache_miss": 2.0, "output": 8.0},
}

# 峰谷规则（与计价.py 一致）：北京时间 09:00–12:00 + 14:00–18:00 为峰，
# 周六周日全天为谷。谷价 = 峰价 × 0.5。
BEIJING = timezone(timedelta(hours=8))
VALLEY_FACTOR = 0.5

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


def is_peak(ts):
    """按北京时间判断峰/谷。无时间戳时按当前时刻。

    周六、周日全天算谷；工作日只有 09:00–12:00 和 14:00–18:00 是峰。
    """
    t = ts or datetime.now(timezone.utc)
    if t.tzinfo is None:                      # transcript 里偶尔是 naive 时间
        t = t.replace(tzinfo=timezone.utc)
    t = t.astimezone(BEIJING)
    if t.weekday() >= 5:
        return False
    return 9 <= t.hour < 12 or 14 <= t.hour < 18


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
        # 按峰/谷分桶：DeepSeek 谷价 = 峰价的一半，逐条按记录时间归属，
        # 这样跨峰谷的会话也能算对（只看「当前时刻」会把整段错算成一档）。
        "peak": {"in": 0, "r": 0, "c": 0, "out": 0},
        "valley": {"in": 0, "r": 0, "c": 0, "out": 0},
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
                u_in = usage.get("input_tokens") or 0
                u_r = usage.get("cache_read_input_tokens") or 0
                u_c = usage.get("cache_creation_input_tokens") or 0
                u_out = usage.get("output_tokens") or 0
                st["in_tok"] += u_in
                st["cache_r"] += u_r
                st["cache_c"] += u_c
                st["out_tok"] += u_out
                st["api_reqs"] += 1
                bucket = st["peak" if is_peak(ts) else "valley"]
                bucket["in"] += u_in
                bucket["r"] += u_r
                bucket["c"] += u_c
                bucket["out"] += u_out

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

    # 老缓存文件里只有汇总 token、没有峰谷分桶。把汇总值按 transcript 的
    # 最后修改时刻一次性归桶（近似），否则历史会话会突然变成 ¥0。
    for key in ("peak", "valley"):
        st.setdefault(key, {"in": 0, "r": 0, "c": 0, "out": 0})
    empty_buckets = not any(st[k][f] for k in ("peak", "valley")
                            for f in ("in", "r", "c", "out"))
    legacy = (st.get("in_tok") or 0, st.get("cache_r") or 0,
              st.get("cache_c") or 0, st.get("out_tok") or 0)
    if empty_buckets and any(legacy):
        try:
            legacy_ts = datetime.fromtimestamp(os.path.getmtime(tpath), timezone.utc)
        except Exception:
            legacy_ts = None
        b = st["peak" if is_peak(legacy_ts) else "valley"]
        b["in"], b["r"], b["c"], b["out"] = legacy

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

    def bucket_cost(b):
        return (b["r"] / 1e6) * p["cache_hit"] \
            + ((b["in"] + b["c"]) / 1e6) * p["cache_miss"] \
            + (b["out"] / 1e6) * p["output"]

    cny = bucket_cost(st["peak"]) + bucket_cost(st["valley"]) * VALLEY_FACTOR

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
    # 🔴 口径与 agy 状态栏（~/bin/agy状态栏.py）严格对齐：只用 transcript 里
    #    逐条 assistant usage 累加的 `命中 / (命中 + 未命中)`，**不再采用** CC
    #    自报的 `prompt_cache.hit_ratio`。
    #    原因：hit_ratio 是 CC 内部的请求级口径，和 agy 那边的 token 加权口径
    #    对不上（实测同一会话 96.87% vs 96.97%，别的会话能差几个点）；
    #    两块状态栏并排看时会显示两个数。
    #    `cache_creation` 在走 DeepSeek 时恒为 0（本机实测），保留在分母里只为
    #    兼容将来接 Anthropic 原生；agy 那边没有这一项，等价于命中 + 未命中。
    total_in = st["cache_r"] + st["in_tok"] + st["cache_c"]
    hit = (st["cache_r"] / total_in * 100) if total_in else 0
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
