"""`argus.py doctor`: check that everything a scheduled run needs is in place."""
import json
import os
import shutil
import subprocess
import sys
import urllib.parse

from . import deliver, render
from .settings import unresolved_env
from .sources import FETCHERS
from .util import http_get


def run(cfg, send_test=False):
    problems = 0

    def check(ok, label, hint=""):
        nonlocal problems
        print(f"  {'✓' if ok else '✗'} {label}" + ("" if ok or not hint else f"  → {hint}"))
        problems += 0 if ok else 1

    check(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]}", "Python 3.9+ is required")
    check(bool(shutil.which("curl")), "curl available", "install curl")
    print(f"  · config: {cfg.config_path}   timezone: {cfg['timezone']}   send hour: {cfg['schedule']['hour']}")

    ctx = cfg.path(cfg["profile"]["context_file"])
    check(ctx.exists(), f"profile context {ctx}", "create it from profiles/example/context.md")

    backend = cfg["llm"]["backend"]
    if backend == "claude-cli":
        ok = bool(shutil.which("claude"))
        check(ok, "claude CLI on PATH", "install Claude Code; log in, or set ANTHROPIC_API_KEY")
        if ok:
            out = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
            print(f"  · {out}")
            try:
                auth = json.loads(subprocess.run(["claude", "auth", "status"], capture_output=True, text=True).stdout)
            except (json.JSONDecodeError, OSError):
                auth = {}
            check(auth.get("loggedIn", True) or os.environ.get("ANTHROPIC_API_KEY"), "claude logged in",
                  "run `claude` once to log in, or set ANTHROPIC_API_KEY")
            if auth.get("authMethod") == "claude.ai" and not (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
                                                              or os.environ.get("ANTHROPIC_API_KEY")):
                print("  · note: scheduled runs reuse your interactive login, whose token can expire while you are away;"
                      "\n    for unattended runs, create a long-lived token with `claude setup-token` and put"
                      "\n    CLAUDE_CODE_OAUTH_TOKEN=... in .env")
    elif backend == "codex-cli":
        ok = bool(shutil.which("codex"))
        check(ok, "codex CLI on PATH", "install Codex CLI and run `codex login`")
        if ok:
            status = subprocess.run(["codex", "login", "status"], capture_output=True, text=True)
            check(status.returncode == 0, f"codex login: {(status.stdout or status.stderr).strip()[:60]}",
                  "run `codex login` (or `codex login --with-api-key`)")
    elif backend == "agent":
        print("  · agent backend: run jobs from your agent's scheduled task (see AGENTS.md)")
    else:
        check(False, f"llm backend '{backend}'", "use claude-cli, codex-cli or agent")

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        p = urllib.parse.urlparse(proxy)
        print(f"  · proxy: {p.scheme}://{p.hostname}:{p.port} (from the environment or .env; "
              "`schedule install` carries it into the scheduler)")
    for src in cfg["news"]["sources"]:
        if src["type"] not in FETCHERS:
            check(False, f"source '{src['name']}' type {src['type']}", f"known types: {', '.join(FETCHERS)}")
    try:
        http_get("https://export.arxiv.org/api/query?search_query=all:agent&max_results=1", timeout=20)
        check(True, "network: arXiv reachable")
    except Exception as e:
        check(False, "network: arXiv reachable", str(e)[:80])

    if not deliver.connectors(cfg):
        check(False, "delivery connectors", "enable at least one entry in `delivery`")
    for conn in deliver.connectors(cfg):
        missing = unresolved_env(conn)
        check(not missing, f"delivery '{conn.get('name') or conn['type']}'",
              f"set {', '.join(missing)} in .env or the environment" if missing else "")
        if conn["type"] == "command":
            exe = conn.get("run", "").split()[0] if conn.get("run") else ""
            check(bool(exe and shutil.which(exe)), f"command connector executable '{exe}'", "install it or fix `run`")

    if send_test:
        sent = deliver.send_text(cfg, render.ui(cfg)["test"])
        check(sent > 0, f"test message sent through {sent} connector(s)",
              "only webhook and command (with run_text) connectors can send text")
    print("all good" if not problems else f"{problems} problem(s) found")
    return problems == 0
