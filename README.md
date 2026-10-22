# Argus

*A hundred eyes on AI, focused on your project.* (Argus Panoptes, the hundred-eyed watchman of Greek myth.)

**A daily, opinionated digest of AI news, open-source projects and agent papers — judged against _your_ project.**

English | [简体中文](README.zh-CN.md)

Every morning Argus collects ~50 news candidates and ~200 new agent papers, has a model you already use
(Claude Code or Codex) pick and rate what matters, reads the best papers in full, and sends two compact cards
to your chat app:

- **AI Daily** — news grouped by a 1–5 ★ rating (🔥 must read / 👍 recommended / 👀 worth a look), a separate
  🧩 open-source section (GitHub Trending, fast-rising new repos, trending Hugging Face models), and
  🔁 follow-ups on topics you track. Every item is one sentence, plus one sentence on what it means for your
  project when it matters.
- **Agent Papers** — today's trend, 3 papers read in full (problem, mechanism, results, limitations, what it
  means for you — folded away until you want it), and a short "at a glance" list.

What makes it useful rather than another feed:

- **Your context, not generic relevance.** You describe your project once (`profiles/<you>/context.md`):
  components, constraints, current initiatives. Ratings and "🏢 For <project>" notes are written against it.
- **Continuous tracking.** 4★+ stories become tracked topics automatically (or add your own). New developments
  come back as follow-ups; rewrites of old news are dropped, even under a new URL.
- **Critical paper reading.** Full text from arXiv HTML, with scepticism about experiment size, fair baselines
  and reliance on frontier models. Papers that were skipped get one more look if the community picks them up.
- **Bring your own model and channel.** No API key needed if a model CLI is logged in. Delivery through
  webhooks or any CLI you already use. Python standard library only.

## Quick start

```bash
git clone https://github.com/AlohomoraC/Argus.git && cd Argus
```

**Option A — let your coding agent do it (recommended).** Open the folder in Claude Code or Codex and say
*"set up Argus for me"*. The agent follows [`AGENTS.md`](AGENTS.md): it asks about your project and chat app,
writes your config, runs a dry run, shows you a sample, and installs the schedule.

**Option B — by hand.**

```bash
cp config.example.json config.json            # edit: timezone, schedule.hour, language, profile, llm, delivery
mkdir -p profiles/me && cp profiles/example/context.md profiles/me/context.md   # describe your project
cp .env.example .env                          # webhook URLs and other secrets referenced as ${VAR}
python3 argus.py doctor                       # checks tools, network, connectors
python3 argus.py run --dry-run                # writes out/dry-run/*.md|html, sends nothing
python3 argus.py doctor --send-test           # one test message
python3 argus.py schedule install             # hourly launchd (macOS) / crontab (Linux) wake-up
```

Requirements: Python 3.9+, `curl`, and one of: [Claude Code](https://code.claude.com) (`claude`),
[Codex CLI](https://github.com/openai/codex) (`codex`), or an agent product that can run scheduled tasks.

## How it runs

```
OS timer / GitHub Actions / agent scheduled task
  └─ argus.py tick            hourly; each job runs once a day after schedule.hour (your timezone)
       ├─ news:   RSS · Hacker News · GitHub · Hugging Face  → dedupe → 1 model call → card → deliver
       └─ papers: arXiv + HF Daily Papers → screen → read top 3 in full → card → deliver
```

Each job keeps its own done-marker: a failed job retries next hour without resending the other one, and a
laptop that was asleep at send time catches up on wake.

### Model backends (`llm.backend`)

| Backend | How it calls the model | Auth |
|---|---|---|
| `claude-cli` | `claude -p --json-schema …` with all tools disabled | Claude Code login, or `ANTHROPIC_API_KEY` |
| `codex-cli` | `codex exec --output-schema … --sandbox read-only` | `codex login`, or `codex login --with-api-key` |
| `agent` | none — the host agent answers each step (see [`AGENTS.md`](AGENTS.md), section 2) | whatever runs the agent |

Models are set per backend: `"llm": {"claude-cli": {"model": "claude-opus-5-5", "models": {"paper_read": "…"}}}`
(empty = the CLI's default). `models` can override the `news`, `paper_screen` and `paper_read` steps.

### Where it runs

- **Your machine**: `python3 argus.py schedule install`. The computer must be on (or catch up on wake).
- **GitHub Actions**: [`.github/workflows/digest.yml`](.github/workflows/digest.yml) — put your config in the
  `ARGUS_CONFIG_JSON` secret, your context in `ARGUS_CONTEXT_MD`, plus an API key and webhook secrets. Use a
  private fork: the state cache is your reading history.
- **Inside Claude Code / Codex**: schedule a daily task with the prompt from [`AGENTS.md`](AGENTS.md)
  (section 2) and `llm.backend = "agent"`.

## Delivery connectors (`delivery`)

Every run writes `out/<job>-<date>.{json,feishu.json,md,html}` and hands them to each enabled connector.
Delivery succeeds if at least one connector does; failures are reported (and sent as a notice when
`notify_on_failure` is on).

```jsonc
{"type": "file",    "dir": "out/site"}                                   // HTML + Markdown, plus latest-*.html
{"type": "webhook", "format": "feishu", "url": "${FEISHU_WEBHOOK_URL}",  // Feishu / Lark custom bot (card 2.0);
 "secret": "${FEISHU_WEBHOOK_SECRET}"}                                   //   secret enables signing
{"type": "webhook", "format": "slack",   "url": "${SLACK_WEBHOOK_URL}"}  // Slack incoming webhook (mrkdwn)
{"type": "webhook", "format": "discord", "url": "${DISCORD_WEBHOOK_URL}"}
{"type": "webhook", "format": "json",    "url": "${MY_ENDPOINT}"}        // the raw digest, for your own service
{"type": "command",                                                      // any CLI you already use
 "run":      "my-chat-cli send --card {feishu_card}",
 "run_text": "my-chat-cli send --text {text}",                           // optional: failure notices, tests
 "expect_output": "success"}                                             // optional: required substring
```

Command placeholders (shell-quoted): `{feishu_card}` `{markdown}` `{html}` `{json}` (file paths), `{title}`,
`{text}` (a plain-text rendering). `${VAR}` anywhere in the config is read from the environment or `.env`.
Add `"enabled": false` to keep a connector configured but off.

## Configuration reference

| Key | Meaning |
|---|---|
| `timezone`, `schedule.hour` | When jobs become due (IANA zone, local hour). `schedule.label` names the launchd job. |
| `language.output`, `language.ui` | Language the model writes in (free text) · card labels (`en` / `zh`). |
| `profile.label`, `profile.icon`, `profile.context_file` | How "For <project>" notes are labelled and where your context lives. |
| `news.sources[]` | `type`: `rss`, `hn`, `github_trending`, `github_new`, `hf_models`. Common fields: `name`, `max`, `enabled`, `keyword_filter`, `content_chars`, `ignore_window`, `open_source`. |
| `news.interests`, `news.deprioritize` | Free-text lists the model ranks by. |
| `news.max_items`, `max_oss_items`, `max_followups` | Caps per section (items below 3★ are never sent). |
| `papers.*` | `arxiv_query`, `lookback_hours`, `max_deep`, `max_glance`, `fulltext_chars`, `recheck_upvotes`. |
| `tracking.expire_days`, `tracking.pushed_days` | Auto topics archive after N quiet days; repeat-detection window. |
| `paths.state`, `paths.out`, `paths.logs` | Where runtime data goes. |

Unspecified keys fall back to the defaults in [`argus/settings.py`](argus/settings.py).

## Commands

```bash
python3 argus.py run [news|papers|all] [--dry-run] [--backend claude-cli|codex-cli|agent]
python3 argus.py tick                       # scheduled entry point (respects time + done-markers)
python3 argus.py due                        # exit 0 if a job is due (used by CI to skip idle runs)
python3 argus.py track list | add "Name" --known "what we know" | remove <id>
python3 argus.py schedule install | uninstall | print
python3 argus.py doctor [--send-test]
```

## Cost

With `claude-cli`, a typical day is one news call (~50 candidates) plus one screening call and three full-paper
reads — roughly $0.1 for news and $0.5–1.5 for papers, depending on the model. Lower it with a cheaper model in
`llm.<backend>.models.paper_read`, or `papers.max_deep: 2`. On a subscription login the usage counts against
your plan instead.

## Privacy & safety

- Your config, context, secrets, state, outputs and logs are git-ignored. Keep it that way if you fork.
- Fetched pages and papers are untrusted input: the Claude backend runs with no tools, the Codex backend in a
  read-only sandbox, and every prompt marks the input as data. Model output is schema-validated and URLs that
  were not in the input are dropped. In agent mode, follow the rules in `AGENTS.md`.
- Be a polite client: one arXiv API request per run (their limit is one per 3 s); GitHub search is limited to
  10 requests/min without `GITHUB_TOKEN`; GitHub Trending is parsed from HTML and may break if the page changes.
  Digests summarise sources for personal use — link to, don't republish, the originals.

## Development

```bash
python3 -m unittest discover -s tests -t .     # offline, never calls a model
```

See [`AGENTS.md`](AGENTS.md) (section 3) for the code layout and conventions. Contributions welcome —
especially new source types and delivery formats.

## License

[MIT](LICENSE)
