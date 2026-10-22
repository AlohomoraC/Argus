"""Paper job: arXiv agent papers + HF Daily Papers -> LLM screening against the project context ->
full-text reading of the top picks (arXiv HTML) -> render -> deliver -> mark seen / rejected."""
import html
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from string import Template

from . import deliver, render, tracking
from .llm import NeedsAgent
from .settings import ROOT
from .util import clean_text, days_ago, http_get, load_json, save_json, today

ATOM = {"a": "http://www.w3.org/2005/Atom"}
SCREEN_PROMPT = ROOT / "prompts" / "paper_screen.md"
READ_PROMPT = ROOT / "prompts" / "paper_read.md"


def arxiv_id(s):
    m = re.search(r"(\d{4}\.\d{4,5})", s or "")
    return m.group(1) if m else None


def collect(cfg):
    conf = cfg["papers"]
    since = datetime.now(timezone.utc) - timedelta(hours=conf["lookback_hours"])
    papers = {}
    # arXiv API terms: at most one request every 3 seconds; we make a single call per run.
    query = urllib.parse.urlencode({"search_query": conf["arxiv_query"], "sortBy": "submittedDate",
                                    "sortOrder": "descending", "max_results": conf["arxiv_max"]})
    for e in ET.fromstring(http_get("https://export.arxiv.org/api/query?" + query, timeout=60)).findall("a:entry", ATOM):
        published = datetime.fromisoformat(e.find("a:published", ATOM).text.replace("Z", "+00:00"))
        pid = arxiv_id(e.find("a:id", ATOM).text)
        if pid and published >= since:
            papers[pid] = {"id": pid, "title": " ".join(e.find("a:title", ATOM).text.split()),
                           "abstract": clean_text(e.find("a:summary", ATOM).text, conf["abstract_chars"]),
                           "hf_upvotes": 0}
    # HF Daily Papers adds a community signal and catches papers outside the arXiv query.
    for p in json.loads(http_get("https://huggingface.co/api/daily_papers?limit=100")):
        paper = p["paper"]
        pid = arxiv_id(paper["id"])
        if pid:
            entry = papers.setdefault(pid, {"id": pid, "title": paper["title"],
                                            "abstract": clean_text(paper.get("summary"), conf["abstract_chars"])})
            entry["hf_upvotes"] = paper.get("upvotes", 0)
    return papers


def full_text(pid, limit):
    """Paper body from arXiv's HTML rendering, without references; None if unavailable."""
    try:
        s = http_get(f"https://arxiv.org/html/{pid}", timeout=60).decode("utf-8", "ignore")
    except Exception:
        return None
    if "ltx_document" not in s:
        return None
    body = s[s.find("<article"):] if "<article" in s else s
    cut = body.find('class="ltx_bibliography')
    body = body[:cut] if cut > 0 else body
    body = re.sub(r"(?is)<(script|style|svg|annotation-xml|annotation)[^>]*>.*?</\1>", " ", body)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()[:limit]


def _read(cfg, llm, paper, pick, topic_ids):
    text = full_text(paper["id"], cfg["papers"]["fulltext_chars"])
    prompt = Template(READ_PROMPT.read_text()).safe_substitute(
        context=cfg.context(), reason=pick["reason"], id=paper["id"], title=paper["title"],
        text=text or paper["abstract"], language=cfg["language"]["output"])
    result, cost = llm.structured(f"paper_read:{paper['id']}", prompt, "paper_read")
    result.update(id=paper["id"], title=paper["title"], basis="full_text" if text else "abstract",
                  reason=pick["reason"], url=f"https://arxiv.org/abs/{paper['id']}",
                  topic_id=pick["topic_id"] if pick["topic_id"] in topic_ids else "",
                  rechecked=paper.get("rechecked", False), hf_upvotes=paper.get("hf_upvotes", 0))
    return result, cost


def run(cfg, llm):
    conf = cfg["papers"]
    date = today()
    seen_path, rejected_path = cfg.state / "papers_seen.json", cfg.state / "papers_rejected.json"
    seen, rejected = load_json(seen_path, {}), load_json(rejected_path, {})

    cache = cfg.out / f"papers-candidates-{date}.json"
    if llm.resumable and cache.exists():
        papers = json.loads(cache.read_text())
    else:
        papers = {}
        for pid, p in collect(cfg).items():
            if pid in seen:
                continue
            if pid in rejected:  # screened out before: one second chance if the community picked it up
                if p.get("hf_upvotes", 0) < conf["recheck_upvotes"]:
                    continue
                p["rechecked"] = True
            papers[pid] = p
        save_json(cache, papers)
    print(f"  {len(papers)} candidate papers ({sum(p.get('rechecked', False) for p in papers.values())} rechecked)")
    if not papers:
        print("  no new papers today")
        return False

    candidates = sorted(papers.values(), key=lambda p: -p.get("hf_upvotes", 0))
    screen, cost = llm.structured("paper_screen", Template(SCREEN_PROMPT.read_text()).safe_substitute(
        context=cfg.context(), max_deep=conf["max_deep"], max_glance=conf["max_glance"],
        watchlist=tracking.prompt_block(cfg, date), language=cfg["language"]["output"],
        candidates=json.dumps(candidates, ensure_ascii=False, indent=0)), "paper_screen")
    picks = [d for d in screen["deep_read"] if d["id"] in papers][: conf["max_deep"]]
    picked = {d["id"] for d in picks}
    glance = [g for g in screen["glance"] if g["id"] in papers and g["id"] not in picked][: conf["max_glance"]]
    print(f"  deep read: {sorted(picked)}" + (f" (screen ≈${cost:.3f})" if cost else ""))

    topic_ids = {t["id"] for t in tracking.active(cfg)}
    pending, results = [], []

    def read_one(pick):
        try:
            return _read(cfg, llm, papers[pick["id"]], pick, topic_ids)
        except NeedsAgent as e:  # collect every waiting step so the agent can answer them in one go
            pending.extend(e.pending)
            return None

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = [r for r in pool.map(read_one, picks) if r]
    if pending:
        raise NeedsAgent(pending)

    read = sorted((r for r, _ in results), key=lambda r: -r["stars"])
    # Full reads that turned out weak (< 3 stars) are demoted to the glance list.
    glance = [{"id": r["id"], "title_local": r["title_local"], "one_liner": r["one_liner"]}
              for r in read if r["stars"] < 3] + glance
    read = [r for r in read if r["stars"] >= 3]
    report = {"date": date, "trend": screen["trend"], "candidate_count": len(papers), "papers": read, "glance": glance}

    doc = render.papers_doc(cfg, report)
    paths = deliver.write_artifacts(cfg, "papers", date, report, doc)
    if cfg.dry_run:
        print(f"  dry run: artifacts in {cfg.out} (nothing sent)")
        return True
    deliver.deliver(cfg, doc, paths)

    shown = {p["id"] for p in read} | {g["id"] for g in glance}
    for pid, p in papers.items():  # a rechecked paper gets only one second chance
        if pid in shown or p.get("rechecked"):
            seen.setdefault(pid, date)
            rejected.pop(pid, None)
        else:
            rejected.setdefault(pid, date)
    cutoff = days_ago(date, conf["seen_days"])
    save_json(seen_path, {k: v for k, v in seen.items() if v >= cutoff})
    save_json(rejected_path, {k: v for k, v in rejected.items() if v >= cutoff})
    tracking.apply_papers(cfg, report)
    return True
