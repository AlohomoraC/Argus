"""Small shared helpers: HTTP, text cleanup, JSON files, dates, markdown snippets."""
import html
import json
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

UA = "Mozilla/5.0 (compatible; argus/0.1)"


def http_get(url, timeout=25, headers=None):
    """GET via curl: the macOS system Python ships an old OpenSSL that fails TLS with some hosts."""
    cmd = ["curl", "-sSL", "--fail", "--compressed", "-m", str(timeout), "-A", UA]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    return subprocess.run(cmd + [url], capture_output=True, check=True).stdout


def clean_text(s, limit):
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s or "", flags=re.S | re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    s = re.sub(r"\s+", " ", s).strip()
    return s[:limit] + ("…" if len(s) > limit else "")


def load_json(path, default):
    path = Path(path)
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def today():
    return datetime.now().strftime("%Y-%m-%d")


def days_ago(date, n):
    return (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=n)).strftime("%Y-%m-%d")


def days_between(start, end):
    """Inclusive day count: a topic created today is on day 1."""
    return (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days + 1


def stars(n):
    n = max(1, min(5, int(n)))
    return "★" * n + "☆" * (5 - n)


def link_text(s):
    """Square brackets would break [text](url) markdown links."""
    return s.replace("[", "［").replace("]", "］")
