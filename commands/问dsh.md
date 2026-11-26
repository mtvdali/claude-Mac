---
description: 把任务交给 DeepSeek Harness (dsh) 执行
argument-hint: <要 dsh 做的事>
allowed-tools: Bash(dsh:*), Read
---

把下面的任务交给本机的 DeepSeek Harness (dsh) 执行：

$ARGUMENTS

调用方式：

```sh
dsh headless "<任务>" 2>/dev/null
```

要点：

- 答案在 stdout，诊断在 stderr ⇒ 取纯答案加 `2>/dev/null`
- 默认模型是 `deepseek-flash`，**已经是最便宜的档**，不要改配置
- 若报 `MISSING_CREDENTIAL`，说明缺 `DEEPSEEK_API_KEY`——**把这一点直接告诉用户，不要自己去找密钥**
- 需要更多工具/配置细节时再读 `~/.claude/skills/dsh/工具对照.md`

把 dsh 的输出原样呈现给用户，不要替它润色或改写结论。
