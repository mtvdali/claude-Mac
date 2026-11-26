# 本机环境备忘（手机 · Android + Termux + proot Debian）

## 这是什么机器
- Android 手机，不是 Mac。宿主机是 Termux（`/data/data/com.termux/files/home`）。
- Claude Code 跑在 **proot Debian 容器**里：`proot-distro login debian`，家目录是容器 root 用户的 home，claude 在 `/usr/local/bin/claude`。
- 无 systemd、无 launchctl、无 xcodebuild/swift/plutil/defaults/osascript，也没有 `~/Desktop`、`~/Library`。
  看到这类命令说明是从 Mac 配置抄过来的，**不要执行，直接换等价做法**（如 systemd → 前台 nohup/`termux-wake-lock`）。
- 磁盘充足（约 900G 可用），但 CPU 与内存有限：避免 `find /` 全盘扫、避免长时间全量构建；优先 ripgrep。

## 跨环境路径
- 容器内可直读宿主机：`/data/data/com.termux/files/home/...`
- Termux 侧访问容器文件：`$PREFIX/var/lib/proot-distro/containers/debian/rootfs/...`
- 手机外部存储：`/sdcard`（`/storage/emulated/0`）

## 模型与网络
- 走 DeepSeek 的 Anthropic 兼容端点（`ANTHROPIC_BASE_URL` + `apiKeyHelper`），模型 `deepseek-v4-flash[1m]`。
- `WebSearch` 已被 deny（第三方端点用不了它）。需要联网查资料时，用 `curl` 拉页面/接口，或让用户直接给链接。
- 长任务前先 `termux-wake-lock`，结束时 `termux-wake-unlock`（在 Termux 侧执行，容器内可调用同名命令）。

## 凭证纪律
- 密钥只存在于 `~/.claude/.secrets/*`（600），由 `apiKeyHelper` 读取。
- 绝不 `cat`/`echo`/写进配置、日志、commit、聊天记录；确需校验只比对哈希或长度。
- `settings.json` 里不允许出现 `sk-...` 明文。

## 配置真源
- 可移植配置放在 `~/claude-config/`（git 仓库，跨设备同步）：
  `settings.json`、`CLAUDE.md`、`api-key-helper.sh`、`statusline*.{sh,py}`、`skills/`
- 同步命令：`ccsync pull`（仓库→本机）/ `ccsync push`（本机→仓库）/ `ccsync doctor`（自检）。
- 本机专属、**不进仓库**：`.secrets/`、`history.jsonl`、`projects/`、`sessions/`、`backups/`、`todos/`。

## 状态栏
- `statusline-fast.sh` 是 bash 缓存壳（1 秒内重复调用不 fork Python），`statusline.py` 才是真逻辑。
- 改渲染逻辑改 `statusline.py`；改刷新频率/回退改 `statusline-fast.sh`。

## 回答习惯
- 中文回答；命令给可直接粘贴的单行；改配置前先备份到 `~/.claude/backups/`。
