#!/bin/sh
# Claude Code 的 apiKeyHelper：只从本机 .secrets 读取，绝不写进 settings.json。
# 换机器时只需放好 /data/data/com.termux/files/home/.claude/.secrets/deepseek_token（chmod 600）。
exec cat "$HOME/.claude/.secrets/deepseek_token"
