"""Delivery. Each run writes artifacts (JSON data, Feishu card, Markdown, HTML), then hands them to the
connectors listed in config `delivery`:

  {"type": "file",    "dir": "out/site"}                       copy HTML/Markdown into a folder (+ latest.html)
  {"type": "webhook", "format": "feishu|slack|discord|json",   POST to a chat-bot webhook; Feishu/Lark `secret`
   "url": "${WEBHOOK_URL}", "secret": "${WEBHOOK_SECRET}"}     enables signature verification
  {"type": "command", "run": "...{feishu_card}...",            run any CLI you already use; placeholders are
   "run_text": "...{text}...", "expect_output": "..."}         shell-quoted paths/values, see README

Delivery counts as successful when at least one connector succeeds; failures are reported, not swallowed.
"""
import base64
import hashlib
import hmac
import json
import shlex
import shutil
import subprocess
import time
import urllib.request

from . import render
from .settings import ENV_REF


class DeliveryError(RuntimeError):
    pass


def write_artifacts(cfg, job, date, data, doc):
    cfg.out.mkdir(parents=True, exist_ok=True)
    base = cfg.out / f"{job}-{date}"
    paths = {"json": base.with_suffix(".json"), "feishu_card": base.with_suffix(".feishu.json"),
             "markdown": base.with_suffix(".md"), "html": base.with_suffix(".html")}
    paths["json"].write_text(json.dumps(data, ensure_ascii=False, indent=1))
    paths["feishu_card"].write_text(json.dumps(render.feishu_card(doc), ensure_ascii=False, indent=1))
    paths["markdown"].write_text(render.markdown(doc))
    paths["html"].write_text(render.html_page(doc))
    return paths


def _post(url, payload):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", "ignore")
    try:  # Feishu/Lark answer HTTP 200 with a non-zero code on errors
        parsed = json.loads(body)
        if isinstance(parsed, dict) and parsed.get("code") not in (None, 0):
            raise DeliveryError(f"webhook rejected the message: {body[:300]}")
    except json.JSONDecodeError:
        pass
    return body


def _feishu_signed(payload, secret):
    if secret:
        ts = str(int(time.time()))
        sign = base64.b64encode(hmac.new(f"{ts}\n{secret}".encode(), b"", hashlib.sha256).digest()).decode()
        payload = dict(payload, timestamp=ts, sign=sign)
    return payload


def _check_resolved(conn):
    missing = ENV_REF.findall(json.dumps(conn))
    if missing:
        raise DeliveryError(f"unset environment variable(s): {', '.join(sorted(set(missing)))}")


def _webhook(conn, doc=None, paths=None, text=None):
    fmt = conn.get("format", "json")
    if fmt == "feishu":
        payload = ({"msg_type": "text", "content": {"text": text}} if text is not None
                   else {"msg_type": "interactive", "card": render.feishu_card(doc)})
        payload = _feishu_signed(payload, conn.get("secret"))
    elif fmt == "slack":
        payload = {"text": text if text is not None else render.slack(doc)}
    elif fmt == "discord":
        body = text if text is not None else render.plain(doc)
        for i in range(0, len(body), 1900):  # Discord caps messages at 2000 characters
            _post(conn["url"], {"content": body[i:i + 1900]})
        return
    else:
        payload = {"text": text} if text is not None else {"title": doc["title"], "doc": doc,
                                                            "data": json.loads(paths["json"].read_text())}
    _post(conn["url"], payload)


def _command(conn, cfg, doc=None, paths=None, text=None):
    template = conn.get("run_text") if text is not None else conn.get("run")
    if not template:
        return False
    values = {"text": text or ""} if text is not None else {
        **{k: str(v) for k, v in paths.items()}, "title": doc["title"], "text": render.plain(doc)}
    cmd = template
    for k, v in values.items():
        cmd = cmd.replace("{" + k + "}", shlex.quote(v))
    proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=180, cwd=cfg.root)
    output = proc.stdout + proc.stderr
    if proc.returncode != 0 or (conn.get("expect_output") and conn["expect_output"] not in output):
        raise DeliveryError(f"command failed ({proc.returncode}): {output[-500:]}")
    return True


def _file(conn, cfg, paths):
    dest = cfg.path(conn.get("dir", "out/site"))
    dest.mkdir(parents=True, exist_ok=True)
    for key in ("html", "markdown"):
        shutil.copy(paths[key], dest / paths[key].name)
    shutil.copy(paths["html"], dest / f"latest-{paths['html'].name.split('-')[0]}.html")


def connectors(cfg):
    return [c for c in cfg["delivery"] if c.get("enabled", True)]


def deliver(cfg, doc, paths):
    ok, errors = 0, []
    for conn in connectors(cfg):
        name = conn.get("name") or conn["type"]
        try:
            _check_resolved(conn)
            if conn["type"] == "file":
                _file(conn, cfg, paths)
            elif conn["type"] == "webhook":
                _webhook(conn, doc=doc, paths=paths)
            elif conn["type"] == "command":
                _command(conn, cfg, doc=doc, paths=paths)
            else:
                raise DeliveryError(f"unknown connector type {conn['type']!r}")
            ok += 1
            print(f"  delivered via {name}")
        except Exception as e:  # keep trying the other connectors
            errors.append(f"{name}: {e}")
            print(f"  !! delivery via {name} failed: {e}")
    if not ok:
        raise DeliveryError("no connector succeeded: " + "; ".join(errors))
    return errors


def send_text(cfg, text):
    """Short notices (failures, tests) through every connector that supports text."""
    sent = 0
    for conn in connectors(cfg):
        try:
            _check_resolved(conn)
            if conn["type"] == "webhook":
                _webhook(conn, text=text)
                sent += 1
            elif conn["type"] == "command" and _command(conn, cfg, text=text):
                sent += 1
        except Exception as e:
            print(f"  !! could not send notice via {conn.get('name') or conn['type']}: {e}")
    return sent
