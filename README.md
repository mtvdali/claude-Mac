# claude-Mac

macOS 上 Claude Code 的 `~/.claude/` **配置类文件**备份。

## 包含什么

| 路径 | 说明 |
|---|---|
| `settings.json` | 全局设置。**`ANTHROPIC_AUTH_TOKEN` 已替换为占位符**；服务器 IP 与私钥文件名也已打码 |
| `settings.local.json` | 本地权限白名单 |
| `policy-limits.json` | 策略限制（`remote_control` / `routines` / `quick_web_setup` 等开关） |
| `CLAUDE.md` | 全局指令 |
| `commands/` | 12 个中文自定义命令 |
| `themes/` | 4 个主题：catppuccin-mocha / dracula / gruvbox-dark / tokyo-night |
| `statusline.py`、`theme.py` | 自建的状态栏与主题脚本 |
| `plugins/installed_plugins.json` | 已装插件清单 |

## 有意排除

`history.jsonl`、`sessions/`、`projects/`、`telemetry/`、`shell-snapshots/`、`file-history/`
以及各类 `*-cache/` —— 这些含对话历史、会话内容与本地项目路径，属于隐私，不进备份。

## 恢复

```sh
cp settings.json settings.local.json policy-limits.json CLAUDE.md ~/.claude/
cp -R commands themes plugins ~/.claude/
cp statusline.py theme.py ~/.claude/
```

然后打开 `settings.json`，把 `ANTHROPIC_AUTH_TOKEN` 的
`<REDACTED: 见本机 ~/.claude/settings.json>` 换回真实密钥；
`permissions.allow` 里的 `<私钥>` / `<服务器IP>` 两处占位符同理。

## 一个已知的坑

`settings.json` 里写的是 `"theme": "custom:dracula"`，但 `~/.claude.json` 里另有一份
`"theme": "dark-ansi"`（偏好项迁移前的旧位置残留）。**两者哪个真正生效会随版本变化**——
实测过生效的是 `~/.claude.json` 那份。恢复后如果主题不对，先看这两个地方。
