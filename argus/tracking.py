"""Continuous tracking: topics whose follow-up developments are re-flagged ("Follow-ups") instead of being
dropped as already seen.

Topics enter automatically (news items rated ≥4★ that the model marks `track_topic`) or manually
(`argus.py track add`); automatic topics are archived after `tracking.expire_days` without news.
A log of recently pushed items (`tracking.pushed_days`) lets the model skip the same story under a new URL.
"""
import json
import re

from .util import days_ago, days_between, load_json, save_json

MAX_UPDATES = 20  # per-topic history kept on disk


def _watch(cfg):
    return cfg.state / "watchlist.json"


def _pushed(cfg):
    return cfg.state / "pushed.json"


def topics(cfg):
    return load_json(_watch(cfg), [])


def active(cfg):
    return [t for t in topics(cfg) if t["status"] == "active"]


def prompt_block(cfg, today):
    """Compact view of active topics for prompts."""
    return json.dumps([
        {"id": t["id"], "name": t["name"], "kind": t["kind"], "known": t["known"],
         "last_update": t["last_update"], "days_tracked": days_between(t["created"], today)}
        for t in active(cfg)
    ], ensure_ascii=False, indent=0)


def recent_pushed(cfg):
    return [{"date": p["date"], "title": p["title"]} for p in load_json(_pushed(cfg), [])]


def tracked_urls(cfg):
    """URLs attached to active topics may come back past `seen`, so new signals on them can be judged."""
    return {u for t in active(cfg) for u in t.get("urls", [])}


def _new_id(name, existing):
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "topic"
    tid, n = base, 2
    while tid in existing:
        tid, n = f"{base}-{n}", n + 1
    return tid


def add(cfg, name, known, kind, today, url=None, all_topics=None):
    save = all_topics is None
    all_topics = topics(cfg) if save else all_topics
    t = {"id": _new_id(name, {x["id"] for x in all_topics}), "name": name, "kind": kind, "known": known,
         "created": today, "last_update": today, "urls": [url] if url else [], "updates": [], "status": "active"}
    all_topics.append(t)
    if save:
        save_json(_watch(cfg), all_topics)
    return t


def remove(cfg, topic_id):
    all_topics = topics(cfg)
    kept = [t for t in all_topics if t["id"] != topic_id]
    save_json(_watch(cfg), kept)
    return len(kept) < len(all_topics)


def _record_update(t, today, what_new, url):
    t["last_update"] = today
    t["updates"] = (t["updates"] + [{"date": today, "what_new": what_new, "url": url}])[-MAX_UPDATES:]
    if url and url not in t["urls"]:
        t["urls"].append(url)


def _log_pushed(cfg, today, entries):
    cutoff = days_ago(today, cfg["tracking"]["pushed_days"])
    save_json(_pushed(cfg), [p for p in load_json(_pushed(cfg), []) if p["date"] >= cutoff] + entries)


def apply_news(cfg, digest):
    """After a news digest is delivered: record follow-ups, open new auto topics, expire stale ones."""
    today = digest["date"]
    all_topics = topics(cfg)
    by_id = {t["id"]: t for t in all_topics}
    for f in digest.get("followups", []):
        _record_update(by_id[f["followup_of"]], today, f["what_new"], f["url"])
    for u in digest.get("topic_updates", []):
        if u["topic_id"] in by_id:
            by_id[u["topic_id"]]["known"] = u["known"]
    for i in digest["items"]:
        if i.get("track_topic") and i["stars"] >= 4:
            add(cfg, i["track_topic"], i["summary"], "auto", today, i["url"], all_topics)
    cutoff = days_ago(today, cfg["tracking"]["expire_days"])
    for t in all_topics:
        if t["kind"] == "auto" and t["status"] == "active" and t["last_update"] < cutoff:
            t["status"] = "archived"
    save_json(_watch(cfg), all_topics)
    _log_pushed(cfg, today, [{"date": today, "title": i["title"], "url": i["url"]}
                             for i in digest["items"] + digest.get("followups", [])])


def apply_papers(cfg, report):
    """After a paper card is delivered: papers linked to a topic count as its update; all shown papers
    join the pushed log so the news digest does not repeat them."""
    today = report["date"]
    all_topics = topics(cfg)
    by_id = {t["id"]: t for t in all_topics}
    for p in report["papers"]:
        if p.get("topic_id") in by_id:
            _record_update(by_id[p["topic_id"]], today, f"Paper: {p['one_liner']}", p["url"])
    save_json(_watch(cfg), all_topics)
    _log_pushed(cfg, today,
                [{"date": today, "title": f"[paper] {p['title_local']} ({p['title']})", "url": p["url"]}
                 for p in report["papers"]]
                + [{"date": today, "title": f"[paper] {g['title_local']}", "url": f"https://arxiv.org/abs/{g['id']}"}
                   for g in report["glance"]])
