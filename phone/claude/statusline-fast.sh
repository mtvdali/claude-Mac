#!/bin/bash
# Claude Code 状态栏快速包装
# 背景：PRoot 下每次 fork Python 约 0.18s 起步，而状态栏在对话中会高频刷新。
# 策略：缓存有效期内的重复调用走纯 bash 内建路径回放上次渲染结果，
#       不 fork 任何外部命令；过期后才真正执行 Python。
# 原脚本 statusline.py 逻辑完全不变；删除本文件并把 settings.json 的
# statusLine.command 改回原命令即可回退。

CACHE_DIR="/data/data/com.termux/files/home/.claude/.statusline-cache"
CACHE="$CACHE_DIR/render.txt"
EXPIRE="$CACHE_DIR/render.expire"
PY="/usr/bin/python3 /data/data/com.termux/files/home/.claude/statusline.py"

# ---- 命中路径：全部是 bash 内建，零 fork ----
printf -v now '%(%s)T' -1
expire=0
[[ -r "$EXPIRE" ]] && read -r expire < "$EXPIRE"
if [[ -s "$CACHE" ]] && (( now < expire )); then
    printf '%s' "$(<"$CACHE")"
    exit 0
fi

# ---- 未命中：读 stdin、执行 Python、写缓存 ----
input=$(</dev/stdin)
mkdir -p "$CACHE_DIR"
tmp="$CACHE_DIR/render.$$.tmp"
printf '%s' "$input" | $PY > "$tmp" 2>/dev/null
mv -f "$tmp" "$CACHE" 2>/dev/null
printf '%s' "$((now + 1))" > "$EXPIRE"
printf '%s' "$(<"$CACHE")"
