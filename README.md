# claude-Mac

Claude Code + agy 的**可移植配置**：Mac 一份、手机（Termux）一份，clone 下来跑一个脚本就能用。

## 一键安装（新电脑 / 新手机）

```sh
git clone --depth 1 https://github.com/mtvdali/claude-Mac.git ~/claude-Mac
bash ~/claude-Mac/install.sh          # 自动判断 macOS / Termux
bash ~/claude-Mac/install.sh --claude # 只装 Claude
bash ~/claude-Mac/install.sh --agy    # 只装 agy
```

脚本会先备份同名文件成 `*.bak.<时间戳>`，密钥永远不进仓库（见下面「凭据怎么处理」）。

手机端（Termux）前置：`pkg install -y python git openssh`；Mac 端：`python3` 自带即可。

## 目录

| 路径 | 说明 |
|---|---|
| `settings.json` | **Mac** 全局设置。服务器 IP 与私钥文件名已打码；`/Users/ootd` 已替换为 `~`。不存任何密钥 |
| `settings.local.json` | 本地权限白名单 |
| `policy-limits.json` | 策略限制（`remote_control` / `routines` / `quick_web_setup` 等开关） |
| `CLAUDE.md` | 全局指令 |
| `commands/` | 12 个中文自定义命令 |
| `themes/` | 4 个主题：catppuccin-mocha / dracula / gruvbox-dark / tokyo-night |
| `statusline.py`、`theme.py` | 自建的状态栏与主题脚本 |
| `plugins/installed_plugins.json` | 已装插件清单 |
| `agy/settings.json` | **agy 通用配置**（桌面）：模型、中文、verbosity、常用只读命令白名单、`trustedWorkspaces=~` |
| `phone/claude/` | **手机 Claude 配置**（Termux + proot Debian）：settings / CLAUDE.md / statusline（含 fast 缓存壳）/ api-key-helper |
| `phone/agy/settings.json` | **手机 agy 配置**：Termux 家目录信任、手机状态栏命令、`termux-wake-*` 白名单 |
| `install.sh` | 上面那个一键安装脚本 |

`agy` 的配置落在 `~/.gemini/antigravity-cli/settings.json`；手机端额外的
`agy状态栏.py`、网关启动器等属于本机私有件，不在仓库里。


## 凭据怎么处理

`settings.json` **不存任何密钥**。鉴权走 `apiKeyHelper`：

```json
"apiKeyHelper": "~/.claude/api-key-helper.sh"
```

该脚本 `cat` 本机的 `~/.claude/.secrets/deepseek_token`。`~/.claude/.secrets/` **不在**
仓库里，新机器上自己放一份（600）。`api-key-helper.sh` 只是读取器，本身不含密钥，
手机那份（`phone/claude/api-key-helper.sh`）已在仓库里作为模板。


## 有意排除

`history.jsonl`、`sessions/`、`projects/`、`telemetry/`、`shell-snapshots/`、`file-history/`
以及各类 `*-cache/` —— 这些含对话历史、会话内容与本地项目路径，属于隐私，不进备份。

## 手动恢复（不用脚本时）

```sh
cp settings.json settings.local.json policy-limits.json CLAUDE.md statusline.py theme.py ~/.claude/
cp -R commands themes plugins ~/.claude/
mkdir -p ~/.gemini/antigravity-cli && cp agy/settings.json ~/.gemini/antigravity-cli/settings.json
```

然后把 `settings.json` 里 `permissions.allow` 的两处占位符换回真实值：
`<私钥>` → 你的私钥文件名，`<服务器IP>` → 你的服务器地址。

## 手机（Termux）怎么用

```sh
pkg install -y python git openssh
git clone --depth 1 https://github.com/mtvdali/claude-Mac.git ~/claude-Mac
bash ~/claude-Mac/install.sh        # 自动识别 Termux，装 phone/claude + phone/agy
```

- `phone/claude/settings.json` 里的路径是**绝对 Termux 路径**（`/data/data/com.termux/files/home`），
  所有 Termux 机器都一样，不用改。
- 手机 Claude 建议跑在 proot Debian 里（`proot-distro login debian`），
  但 `~/.claude/` 仍放 Termux 家目录，容器里通过 `/data/data/com.termux/files/home/.claude` 读。
- `phone/claude/statusline-fast.sh` 是状态栏的 bash 缓存壳（1 秒内重复调用不 fork Python），
  回退方式：把 `settings.json` 的 `statusLine.command` 改回 `statusline.py`。
- 手机 agy 的 `trustedWorkspaces` 已包含 Termux 家目录两种路径，首次启动不会再卡在「是否信任」。


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
