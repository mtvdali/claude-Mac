#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# claude-Mac 一键安装
#
#   git clone --depth 1 https://github.com/mtvdali/claude-Mac.git ~/claude-Mac
#   bash ~/claude-Mac/install.sh
#
# 会自动判断环境：
#   Termux（手机）→ phone/claude/*  → ~/.claude/ ，phone/agy/settings.json → agy
#   macOS / Linux  → 根目录的 Claude 配置 → ~/.claude/ ，agy/settings.json → agy
#
# 覆盖前统一备份成 <文件>.bak.<时间戳>。密钥永远不进仓库，
# Claude 走 apiKeyHelper，需要你自己放 ~/.claude/.secrets/deepseek_token。
#
# 参数：--claude 只装 Claude；--agy 只装 agy；--dry-run 只看不动手
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DO_CLAUDE=1
DO_AGY=1
DRY=0
for a in "$@"; do
  case "$a" in
    --claude) DO_AGY=0 ;;
    --agy)    DO_CLAUDE=0 ;;
    --dry-run) DRY=1 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "未知参数：$a" >&2; exit 2 ;;
  esac
done

if [ -n "${TERMUX_VERSION:-}" ] || [ -d /data/data/com.termux ] || [ -d "${PREFIX:-}/var/lib/proot-distro" ]; then
  MODE=phone
else
  MODE=mac
fi
SRC_CLAUDE="$REPO"
[ "$MODE" = phone ] && SRC_CLAUDE="$REPO/phone/claude"

CLAUDE_DIR="$HOME/.claude"
AGY_DIR="$HOME/.gemini/antigravity-cli"

say() { printf '%s\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then say "  [dry] $*"; else eval "$@"; fi; }

# 备份后复制（cp -p 保留可执行位）
put() {
  local src="$1" dst="$2"
  [ -f "$src" ] || return 0
  if [ -e "$dst" ] && cmp -s "$src" "$dst"; then
    say "  = $(basename "$dst")（已一致）"; return 0
  fi
  if [ -e "$dst" ]; then
    run "cp -p '$dst' '$dst.bak.$(date +%Y%m%d-%H%M%S)'"
  fi
  run "mkdir -p '$(dirname "$dst")'"
  run "cp -p '$src' '$dst'"
  say "  + $(basename "$dst")"
}

say "环境：${MODE}（${REPO}）"

if [ "$DO_CLAUDE" = 1 ]; then
  say "→ Claude Code 配置"
  for f in settings.json settings.local.json policy-limits.json CLAUDE.md statusline.py theme.py statusline-fast.sh api-key-helper.sh; do
    put "$SRC_CLAUDE/$f" "$CLAUDE_DIR/$f"
  done
  [ -d "$SRC_CLAUDE/commands" ] && run "mkdir -p '$CLAUDE_DIR/commands'" && run "cp -p '$SRC_CLAUDE'/commands/*.md '$CLAUDE_DIR/commands/'" && say "  + commands/*.md"
  [ -d "$SRC_CLAUDE/themes" ] && run "mkdir -p '$CLAUDE_DIR/themes'" && run "cp -p '$SRC_CLAUDE'/themes/*.json '$CLAUDE_DIR/themes/'" && say "  + themes/*.json"
  [ -f "$CLAUDE_DIR/api-key-helper.sh" ] && run "chmod 700 '$CLAUDE_DIR/api-key-helper.sh'"
  run "mkdir -p '$CLAUDE_DIR/.secrets'" && run "chmod 700 '$CLAUDE_DIR/.secrets'"
fi

if [ "$DO_AGY" = 1 ]; then
  say "→ agy 配置"
  if [ "$MODE" = phone ]; then put "$REPO/phone/agy/settings.json" "$AGY_DIR/settings.json"
  else put "$REPO/agy/settings.json" "$AGY_DIR/settings.json"; fi
fi

say ""
say "完成。还差两步（密钥从来不在仓库里）："
say "  1) 放好密钥：  echo '你的 key' > ~/.claude/.secrets/deepseek_token && chmod 600 ~/.claude/.secrets/deepseek_token"
say "  2) 装 agy 后跑：agy   （首次会问你信任哪个目录）"
if [ "$MODE" = mac ]; then
  say "  另：~/.claude/settings.json 里 <私钥>/<服务器IP> 两个占位符换成自己的，或直接删那两行 allow。"
fi
