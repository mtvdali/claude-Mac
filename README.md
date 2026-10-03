# claude-Mac

macOS 上 Claude Code 的 `~/.claude/` **配置类文件**备份。

## 包含什么

| 路径 | 说明 |
|---|---|
| `settings.json` | 全局设置。**服务器 IP 与私钥文件名已打码**；`/Users/ootd` 已替换为 `~`。不存任何密钥 |
| `settings.local.json` | 本地权限白名单 |
| `policy-limits.json` | 策略限制（`remote_control` / `routines` / `quick_web_setup` 等开关） |
| `CLAUDE.md` | 全局指令 |
| `commands/` | 12 个中文自定义命令 |
| `themes/` | 4 个主题：catppuccin-mocha / dracula / gruvbox-dark / tokyo-night |
| `statusline.py`、`theme.py` | 自建的状态栏与主题脚本 |
| `plugins/installed_plugins.json` | 已装插件清单 |

## 凭据怎么处理

`settings.json` **不存任何密钥**。鉴权走 `apiKeyHelper`：

```json
"apiKeyHelper": "~/.claude/api-key-helper.sh"
```

该脚本 `cat` 本机的 `~/.claude/.secrets/deepseek_token`。这两个文件本身
（`api-key-helper.sh`、`.secrets/`）都**不在**备份里，需要在新机器上自备。

## 有意排除

`history.jsonl`、`sessions/`、`projects/`、`telemetry/`、`shell-snapshots/`、`file-history/`
以及各类 `*-cache/` —— 这些含对话历史、会话内容与本地项目路径，属于隐私，不进备份。

## 恢复

```sh
cp settings.json settings.local.json policy-limits.json CLAUDE.md ~/.claude/
cp -R commands themes plugins ~/.claude/
cp statusline.py theme.py ~/.claude/
```

然后把 `settings.json` 里 `permissions.allow` 的两处占位符换回真实值：
`<私钥>` → 你的私钥文件名，`<服务器IP>` → 你的服务器地址。

## 两个已知的坑

**1. 主题字段有两个位置。** `~/.claude.json` 里存着一份 `"theme"`
（偏好项迁移前的旧位置残留）。历史上 `settings.json` 也写过 `"theme": "custom:dracula"`，
**两者哪个生效会随版本变化**，实测生效的是 `~/.claude.json` 那份。
**截至 2026-10-03 的这次备份，`settings.json` 已无 `theme` 字段**，
如有主题异常先查 `~/.claude.json`。

**2. `deny` 会整体推翻 `allow`。** `settings.json` 的 `permissions.deny` 里若写入裸工具名
（如 `WebFetch`、`WebSearch`），会把 `settings.local.json` 中同工具的
`allow` 白名单（包括 `WebFetch(domain:github.com)` 这类）**全部推翻**，
而且该工具会**从会话的工具列表中完全消失**——模型连看都看不到，不是"调用时被拒"。
2026-10-02 实测确认（隔离 HOME 对照：移除 deny 后两个工具即回到列表）。
如果只想限制域名、保留白名单式抓取，就别写裸工具名。
