---
name: argus-setup
description: Set up Argus for the user - interview them about their project, interests, schedule, model backend and chat app, write config.json / profile context / .env, verify with doctor and a dry run, then install the schedule. Use when the user asks to set up, configure, install or personalise Argus or its daily digest.
---

Follow section 1 ("Set up Argus for the user") of `AGENTS.md` in the repository root, step by step.

- Propose defaults instead of asking many questions; one short interview message is enough.
- `config.json`, `.env` and `profiles/<name>/` are git-ignored personal files — never commit them, and never
  echo secrets back.
- Always finish with `python3 argus.py doctor` and `python3 argus.py run --dry-run`, and show the user part of
  `out/dry-run/news-<date>.md` before sending a test message or installing the schedule.
- Ask before `doctor --send-test` (it sends a message) and before `schedule install` (it adds a launchd job or
  crontab entry).
