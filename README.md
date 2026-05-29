# AI OSS Radar

这个目录里是一个今晚可跑、明早可看的 AI 开源项目雷达。

它会监测围绕 Codex、Claude Code、OpenAI/Codex、AI coding agent、MCP、Cursor/Gemini CLI/opencode 等关键词的开源项目和 Hacker News 社区信号，按热度、增长速度、更新频率、相关性和可复用价值打分，然后生成中文可读的 Markdown 报告。

> 说明：你语音里说的 “Cloud” 我先按 “Claude Code” 处理；“NEAI” 我先按 “OpenAI / AI coding agent 生态” 处理。关键词都在 `config/topics.json`，后面可以随时改。

## 运行

```bash
python3 ai_radar.py --days 7 --max-items 25
```

输出：

- `reports/latest.md`：最新报告
- `reports/YYYY-MM-DD-ai-oss-radar.md`：按日期归档的报告
- `data/raw/*.json`：原始抓取和评分数据
- `data/seen_repos.json`：已见项目状态，用来标记下一次运行的新上榜项目

## 自测并发 Gmail

```bash
python3 run_and_notify.py
```

需要先配置 SMTP 环境变量：

```bash
export RADAR_EMAIL_TO="your-address@gmail.com"
export SMTP_USER="your-sender@gmail.com"
export SMTP_PASSWORD="your-gmail-app-password"
```

自动任务也会读取 `config/email.env`，更适合长期运行：

```bash
RADAR_EMAIL_TO=your-address@gmail.com
SMTP_USER=your-sender@gmail.com
SMTP_PASSWORD=your-gmail-app-password
```

Gmail 需要使用 App Password，不要使用主账号密码。测试邮件内容但不真正发送：

```bash
python3 run_and_notify.py --skip-radar --dry-run-email
```

默认不会使用未认证的本地 `sendmail`，因为 Gmail 很可能把这种 `localdomain` 发件人过滤掉。确实想兜底尝试的话，可以设置 `RADAR_ALLOW_SENDMAIL_FALLBACK=true`，但长期稳定运行还是建议补上 Gmail App Password。

运行后会写入：

- `reports/last_email.txt`：最近一次邮件正文和发送状态

## 可选环境变量

如果 GitHub 匿名限流，设置一个 token 会更稳：

```bash
export GITHUB_TOKEN=ghp_xxx
```

## 云端运行

已经内置 GitHub Actions workflow：

- [.github/workflows/daily-radar.yml](.github/workflows/daily-radar.yml)
- [docs/CLOUD_DEPLOY.md](docs/CLOUD_DEPLOY.md)

推到 GitHub 私有仓库后，在 repository secrets 里配置：

- `RADAR_EMAIL_TO`
- `SMTP_USER`
- `SMTP_PASSWORD`
- 可选：`GH_SEARCH_TOKEN`

之后电脑关机也会每天云端跑并发 Gmail 简报。

## 怎么用报告

优先看 `Executive Picks` 和 `Quick Leverage Notes`：

- 能直接跑 demo 的，先 clone 试跑。
- prompt、skills、commands 类项目，优先抽成自己的 Codex/Claude 模板。
- MCP 类项目，优先看接口和接入方式。
- observability 类项目，优先复用 token、成本、会话监控。
- 多 agent 编排类项目，优先研究任务拆分、上下文传递和失败恢复。

## 下一步增强

- 接 Product Hunt / Reddit / GitHub Trending 抓取。
- 加 Slack、邮件或飞书推送。
- 加 LLM 摘要：自动读 README，生成“能不能为我所用”的短评。
- 加去重和项目画像缓存，按每日新增 stars 做真正的增长曲线。
