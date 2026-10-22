"""News job: collect candidates from all sources -> one structured LLM pass -> render -> deliver -> mark seen."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from string import Template

from . import deliver, render, tracking
from .settings import ROOT
from .sources import FETCHERS
from .util import days_ago, load_json, save_json, today

PROMPT = ROOT / "prompts" / "news.md"


def collect(cfg):
    conf = cfg["news"]
    seen = load_json(cfg.state / "seen.json", {})
    tracked = tracking.tracked_urls(cfg)
    since = datetime.now(timezone.utc) - timedelta(hours=conf["lookback_hours"])
    candidates = []
    for src in conf["sources"]:
        if not src.get("enabled", True):
            continue
        started = time.time()
        try:
            items = FETCHERS[src["type"]](src, since)
        except Exception as e:  # one broken source must not kill the digest
            print(f"  ✗ {src['name']}: {type(e).__name__}: {str(e)[:100]}")
            continue
        fresh = [i for i in items if i["url"] and (i["url"] not in seen or i["url"] in tracked)][: src.get("max", 10)]
        for i in fresh:
            i["source"] = src["name"]
            if src.get("open_source"):
                i["open_source"] = True
            if i["url"] in seen:
                i["previously_seen"] = True
        candidates += fresh
        print(f"  ✓ {src['name']}: {len(fresh)} new / {len(items)} fetched ({time.time() - started:.1f}s)")

    unique, keys = [], set()  # same story linked from several sources: keep the first
    for c in candidates:
        key = re.sub(r"[?#].*$", "", c["url"]).rstrip("/")
        if key not in keys:
            keys.add(key)
            unique.append(c)
    return unique


def summarize(cfg, llm, candidates, date):
    conf = cfg["news"]
    prompt = Template(PROMPT.read_text()).safe_substitute(
        context=cfg.context(),
        interests="\n".join(f"- {x}" for x in conf["interests"]) or "- (none given)",
        deprioritize="\n".join(f"- {x}" for x in conf["deprioritize"]) or "- (none given)",
        max_items=conf["max_items"], max_oss_items=conf["max_oss_items"], max_followups=conf["max_followups"],
        language=cfg["language"]["output"],
        watchlist=tracking.prompt_block(cfg, date), pushed_days=cfg["tracking"]["pushed_days"],
        recent_pushed=json.dumps(tracking.recent_pushed(cfg), ensure_ascii=False, indent=0),
        candidates=json.dumps(candidates, ensure_ascii=False, indent=1),
    )
    digest, cost = llm.structured("news", prompt, "news")

    for i in digest.pop("oss_items", []):
        i["category"] = "open_source"
        digest["items"].append(i)
    known = {c["url"] for c in candidates}  # guard against invented links
    dropped = [i["url"] for i in digest["items"] if i["url"] not in known]
    kept = sorted((i for i in digest["items"] if i["url"] in known and i["stars"] >= 3), key=lambda i: -i["stars"])
    topic_ids = {t["id"] for t in tracking.active(cfg)}
    for i in kept:  # a follow-up must point at a real topic; otherwise treat it as an ordinary item
        if i["followup_of"] not in topic_ids:
            i["followup_of"] = i["what_new"] = ""
    followups = [i for i in kept if i["followup_of"]][: conf["max_followups"]]
    rest = [i for i in kept if not i["followup_of"]]
    news = [i for i in rest if i["category"] != "open_source"][: conf["max_items"]]
    oss = [i for i in rest if i["category"] == "open_source"][: conf["max_oss_items"]]
    digest.update(
        items=news + oss, followups=followups, date=date, candidate_count=len(candidates),
        source_count=len({c["source"] for c in candidates}),
        topic_updates=[u for u in digest["topic_updates"] if u["topic_id"] in {f["followup_of"] for f in followups}],
    )
    print(f"  {len(news)} news + {len(oss)} open source + {len(followups)} follow-ups"
          + (f" (≈${cost:.3f})" if cost else "") + (f"; dropped {len(dropped)} unknown urls" if dropped else ""))
    return digest


def mark_seen(cfg, candidates, date):
    """Every candidate counts as seen (not only the picked ones) so tomorrow only sees genuinely new items."""
    path = cfg.state / "seen.json"
    seen = load_json(path, {})
    for c in candidates:
        seen.setdefault(c["url"], date)
    cutoff = days_ago(date, cfg["news"]["seen_days"])
    save_json(path, {u: d for u, d in seen.items() if d >= cutoff})


def run(cfg, llm):
    """Returns True if something was delivered (or would be, in a dry run)."""
    date = today()
    cache = cfg.out / f"news-candidates-{date}.json"
    if llm.resumable and cache.exists():  # agent mode re-runs must see the same inputs
        candidates = json.loads(cache.read_text())
    else:
        candidates = collect(cfg)
        save_json(cache, candidates)
    print(f"  {len(candidates)} candidates")
    if not candidates:
        print("  nothing new today")
        return False
    digest = summarize(cfg, llm, candidates, date)
    doc = render.news_doc(cfg, digest)
    paths = deliver.write_artifacts(cfg, "news", date, digest, doc)
    if cfg.dry_run:
        print(f"  dry run: artifacts in {cfg.out} (nothing sent)")
        return True
    deliver.deliver(cfg, doc, paths)
    mark_seen(cfg, candidates, date)
    tracking.apply_news(cfg, digest)
    return True
