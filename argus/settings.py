"""Configuration: config.json (+ defaults), .env loading, ${ENV} substitution, paths and timezone."""
import copy
import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULTS = {
    "timezone": "UTC",
    "schedule": {"hour": 8, "label": "io.github.argus"},
    "language": {"output": "English", "ui": "en"},
    "profile": {"label": "my project", "icon": "🏢", "context_file": "profiles/example/context.md"},
    "llm": {
        "backend": "claude-cli", "timeout_seconds": 900,
        # Model names belong to a backend; empty = that CLI's own default. `models` overrides per step
        # (news / paper_screen / paper_read).
        "claude-cli": {"model": "", "models": {}},
        "codex-cli": {"model": "", "models": {}, "ignore_user_config": True},
    },
    "news": {
        "enabled": True, "lookback_hours": 30, "max_items": 10, "max_oss_items": 5, "max_followups": 5,
        "seen_days": 30, "interests": [], "deprioritize": [], "sources": [],
    },
    "papers": {
        "enabled": True, "lookback_hours": 48, "max_deep": 3, "max_glance": 4, "arxiv_max": 400,
        "abstract_chars": 700, "fulltext_chars": 120000, "recheck_upvotes": 30, "seen_days": 60,
        "arxiv_query": "(cat:cs.AI OR cat:cs.CL OR cat:cs.MA OR cat:cs.SE OR cat:cs.LG OR cat:cs.HC) AND "
                       "(abs:agent OR abs:agents OR abs:agentic OR abs:\"multi-agent\" OR abs:\"tool use\")",
    },
    "tracking": {"expire_days": 30, "pushed_days": 7},
    "delivery": [{"type": "file", "dir": "out/site"}],
    "notify_on_failure": True,
    "paths": {"state": "state", "out": "out", "logs": "logs"},
}

ENV_REF = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _merge(base, override):
    out = copy.deepcopy(base)
    for k, v in override.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _substitute(value):
    """Replace ${VAR} with environment values; unknown variables stay as-is so `doctor` can report them."""
    if isinstance(value, str):
        return ENV_REF.sub(lambda m: os.environ.get(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_substitute(v) for v in value]
    if isinstance(value, dict):
        return {k: _substitute(v) for k, v in value.items()}
    return value


def load_dotenv(path):
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip("'\""))


class Config(dict):
    """The merged config dict plus resolved paths. `dry_run` redirects outputs to out/dry-run."""

    def __init__(self, data, root=ROOT, config_path=None):
        super().__init__(data)
        self.root = Path(root)
        self.config_path = config_path
        self.dry_run = False

    def path(self, rel):
        p = Path(rel)
        return p if p.is_absolute() else self.root / p

    @property
    def state(self):
        return self.path(self["paths"]["state"])

    @property
    def out(self):
        base = self.path(self["paths"]["out"])
        return base / "dry-run" if self.dry_run else base

    @property
    def logs(self):
        return self.path(self["paths"]["logs"])

    def model_for(self, backend, task):
        """llm.<backend>.models.<step> (news / paper_screen / paper_read), else llm.<backend>.model."""
        conf = self["llm"].get(backend, {})
        return conf.get("models", {}).get(task.split(":")[0]) or conf.get("model", "")

    def context(self):
        p = self.path(self["profile"]["context_file"])
        return p.read_text() if p.exists() else ""


def load(config_path=None, root=ROOT):
    root = Path(root)
    load_dotenv(root / ".env")
    config_path = Path(config_path or os.environ.get("ARGUS_CONFIG") or root / "config.json")
    if not config_path.exists():
        raise SystemExit(f"No config at {config_path}. Copy config.example.json to config.json "
                         "(or ask your coding agent to run the setup in AGENTS.md).")
    cfg = Config(_substitute(_merge(DEFAULTS, json.loads(config_path.read_text()))), root, config_path)
    os.environ["TZ"] = cfg["timezone"]  # all dates (file names, "today", topic ages) follow the reader's clock
    time.tzset()
    return cfg


def unresolved_env(value, found=None):
    """List ${VAR} references that are still unresolved anywhere in the config."""
    found = set() if found is None else found
    if isinstance(value, str):
        found.update(ENV_REF.findall(value))
    elif isinstance(value, list):
        for v in value:
            unresolved_env(v, found)
    elif isinstance(value, dict):
        for v in value.values():
            unresolved_env(v, found)
    return sorted(found)
