# AI Radar

**每天一份有观点的 AI 简报：新闻、开源项目和 Agent 论文，按 _你的_ 项目来判断价值。**

[English](README.md) | 简体中文

AI Radar 每天收集约 50 条新闻候选和约 200 篇新的 agent 论文，交给你已经在用的模型（Claude Code 或 Codex）
挑选和打分，精读最好的几篇论文，然后往你的聊天工具推送两张精简的卡片：

- **AI 日报**：新闻按 1–5 星分组（🔥 必读 / 👍 推荐 / 👀 值得一看），另有 🧩 开源项目分组（GitHub 日榜、
  快速上升的新项目、HF 热门模型），以及你所追踪主题的 🔁 追踪更新。每条只有一句话；和你的项目相关时，再加一句启示。
- **Agent 论文精读**：今日趋势，3 篇全文精读（问题、机制、结果、局限、对你的意义，默认折叠），以及速览。

它和普通信息流的区别：

- **按你的背景判断。** 你只需写一次项目背景（`profiles/<你>/context.md`）：模块、约束、正在做的专项。
  星级和「🏢 对 <项目>」都是对照它来写的。
- **持续追踪。** 4 星及以上的事件自动成为追踪主题（也可以手动添加），有新进展时作为「追踪更新」再提醒；
  换个链接的旧闻会被过滤掉。
- **批判性读论文。** 读 arXiv HTML 全文，会审视实验规模、对比是否公平、是否依赖前沿模型；初筛落选的论文，
  如果之后社区热度上升，还会重新评估一次。
- **模型和渠道都用你自己的。** CLI 已登录就不需要 API Key；推送支持 Webhook，也能接入你已有的任何命令行工具；
  只依赖 Python 标准库。

## 快速开始

```bash
git clone <本仓库> ai-radar && cd ai-radar
```

**方式 A：让你的编码 agent 来配置（推荐）。** 在 Claude Code 或 Codex 里打开这个目录，说一句「帮我配置 AI Radar」。
agent 会按照 [`AGENTS.md`](AGENTS.md) 询问你的项目和推送渠道，生成配置，跑一次 dry run 给你看样例，然后安装定时任务。

**方式 B：手动配置。**

```bash
cp config.example.json config.json            # 修改时区、推送时间、语言、profile、llm、delivery
mkdir -p profiles/me && cp profiles/example/context.md profiles/me/context.md   # 写你的项目背景
cp .env.example .env                          # Webhook 地址等密钥（配置里用 ${VAR} 引用）
python3 radar.py doctor                       # 检查工具、网络、连接器
python3 radar.py run --dry-run                # 生成 out/dry-run/*.md|html，不发送
python3 radar.py doctor --send-test           # 发一条测试消息
python3 radar.py schedule install             # 每小时唤醒（macOS 用 launchd，Linux 用 crontab）
```

界面语言设为 `"language": {"ui": "zh"}`，输出语言设为 `"output": "简体中文 (Simplified Chinese)"`，卡片就是中文的。

依赖：Python 3.9+、`curl`，以及以下其一：Claude Code（`claude`）、Codex CLI（`codex`），或者支持定时任务的 agent 产品。

## 三种模型后端

| 后端 | 调用方式 | 认证 |
|---|---|---|
| `claude-cli` | `claude -p --json-schema …`，禁用所有工具 | Claude Code 登录状态，或 `ANTHROPIC_API_KEY` |
| `codex-cli` | `codex exec --output-schema … --sandbox read-only` | `codex login`，或 `codex login --with-api-key` |
| `agent` | 不调用 CLI，由宿主 agent 自己回答每一步（见 `AGENTS.md` 第 2 节） | 由运行 agent 的产品负责 |

## 三种运行位置

- **本机**：`python3 radar.py schedule install`，需要电脑开着；睡眠中错过的会在唤醒后补发。
- **GitHub Actions**：见 [`.github/workflows/digest.yml`](.github/workflows/digest.yml) 文件开头的说明。建议用私有 fork，
  因为状态缓存就是你的阅读记录。
- **Claude Code / Codex 定时任务**：设 `llm.backend = "agent"`，并使用 `AGENTS.md` 里的定时任务提示词。

连接器、配置项、命令和成本的完整说明见 [英文 README](README.md)。

## 隐私与安全

- 配置、背景、密钥、状态、产物和日志都在 `.gitignore` 里，fork 时请保持。
- 抓取的网页和论文都是不可信输入：Claude 后端禁用所有工具，Codex 后端使用只读沙箱，prompt 里也会明确标注为数据；
  模型输出会做 schema 校验，不在输入里的链接会被丢弃。

## 许可证

[MIT](LICENSE)
