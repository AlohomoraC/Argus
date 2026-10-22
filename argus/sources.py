"""Source fetchers. Each takes (src_config, since_datetime) and returns a list of
{"title", "url", "published", "text"} dicts. Add a new source type by adding a function to FETCHERS."""
import json
import os
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from .util import clean_text, http_get

# Only for general-purpose sources (Hacker News, or any source with "keyword_filter": true).
AI_PATTERN = re.compile(
    r"\b(ai|llms?|gpt[-\w]*|claude|gemini|llama|mistral|qwen|deepseek|openai|anthropic|deepmind|"
    r"agents?|agentic|mcp|rag|transformers?|diffusion|inference|fine-?tun\w*|rlhf|embeddings?|"
    r"neural|machine learning|copilot|cursor|codex|benchmarks?|tokens?|reasoning|multimodal|"
    r"hugging ?face|vllm|ollama|gpu|cuda|nvidia|language models?)\b"
    r"|智能体|大模型|模型|人工智能|生成式|多模态|推理|算力",  # CJK has no word boundaries
    re.I,
)


def parse_date(s):
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _child_text(el, *names):
    for c in el:
        if _local(c.tag) in names and (c.text or "").strip():
            return c.text
    return ""


def parse_feed(data, src, since):
    """RSS 2.0 and Atom."""
    limit = src.get("content_chars", 600)
    items = []
    for el in ET.fromstring(data).iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        link = _child_text(el, "link")
        if not link:  # Atom: <link href=... rel="alternate"/>
            for c in el:
                if _local(c.tag) == "link" and c.get("rel", "alternate") == "alternate":
                    link = c.get("href", "")
                    break
        published = parse_date(_child_text(el, "pubDate", "published", "updated", "date"))
        if not src.get("ignore_window") and published and published < since:
            continue
        title = clean_text(_child_text(el, "title"), 200)
        if src.get("keyword_filter") and not AI_PATTERN.search(title):
            continue
        body = _child_text(el, "encoded", "content") or _child_text(el, "description", "summary")
        items.append({"title": title, "url": link.strip(), "text": clean_text(body, limit),
                      "published": published.isoformat() if published else None})
    return items


def fetch_rss(src, since):
    return parse_feed(http_get(src["url"]), src, since)


def fetch_hn(src, since):
    url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode({
        "tags": "story", "hitsPerPage": 200,
        "numericFilters": f"created_at_i>{int(since.timestamp())},points>={src.get('min_points', 50)}",
    })
    hits = sorted(json.loads(http_get(url))["hits"], key=lambda h: -h.get("points", 0))
    items = []
    for h in hits:
        title = h.get("title") or ""
        if not AI_PATTERN.search(title):
            continue
        discussion = f"https://news.ycombinator.com/item?id={h['objectID']}"
        items.append({"title": title, "url": h.get("url") or discussion, "published": h.get("created_at"),
                      "text": f"{h.get('points', 0)} points, {h.get('num_comments', 0)} comments. "
                              f"Discussion: {discussion}"})
    return items


def parse_github_trending(page, src):
    items = []
    for a in re.findall(r'<article class="Box-row">(.*?)</article>', page, re.S):
        repo = re.search(r'<h2[^>]*>.*?href="/([^"]+)"', a, re.S)
        if not repo:
            continue
        desc = re.search(r'<p class="col-9[^"]*">(.*?)</p>', a, re.S)
        desc = clean_text(desc.group(1), 300) if desc else ""
        if src.get("keyword_filter") and not AI_PATTERN.search(f"{repo.group(1)} {desc}"):
            continue
        lang = re.search(r'itemprop="programmingLanguage">([^<]*)<', a)
        total = re.search(r'href="/[^"]+/stargazers"[^>]*>.*?</svg>\s*([\d,]+)', a, re.S)
        today = re.search(r"([\d,]+)\s+stars? today", a)
        items.append({
            "title": f"{repo.group(1)}: {desc}"[:200], "url": f"https://github.com/{repo.group(1)}",
            "published": None,
            "text": f"GitHub Trending (daily). Stars: {total.group(1) if total else '?'} total, "
                    f"+{today.group(1) if today else '?'} today; language {lang.group(1) if lang else '?'}. {desc}",
        })
    return items


def fetch_github_trending(src, since):
    """github.com/trending has no API: parse the server-rendered page (may break if GitHub changes markup)."""
    return parse_github_trending(http_get("https://github.com/trending?since=daily").decode("utf-8", "ignore"), src)


def fetch_github_new(src, since):
    """Repos created in the last N days on agent/LLM topics, ranked by stars: projects just taking off.
    Unauthenticated GitHub search allows 10 requests/min; set GITHUB_TOKEN to raise it."""
    days = src.get("created_within_days", 7)
    created = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    q = f"{src.get('query', 'agent OR mcp OR llm')} created:>{created} stars:>={src.get('min_stars', 200)}"
    url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
        {"q": q, "sort": "stars", "order": "desc", "per_page": 30})
    headers = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}"} if os.environ.get("GITHUB_TOKEN") else {}
    return [{
        "title": f"{r['full_name']}: {r.get('description') or ''}"[:200], "url": r["html_url"],
        "published": r["created_at"],
        "text": f"New repo (last {days} days). Stars: {r['stargazers_count']}, created {r['created_at'][:10]}, "
                f"language {r.get('language') or '?'}, topics: {', '.join(r.get('topics', [])[:8])}. "
                + clean_text(r.get("description"), 300),
    } for r in json.loads(http_get(url, headers=headers))["items"]]


def fetch_hf_models(src, since):
    """Trending open-weight models on Hugging Face, limited to recent ones of the configured pipeline types."""
    newest = datetime.now(timezone.utc) - timedelta(days=src.get("max_age_days", 30))
    pipelines = set(src.get("pipelines", []))
    items = []
    for m in json.loads(http_get("https://huggingface.co/api/models?sort=trendingScore&limit=60")):
        created = parse_date(m.get("createdAt"))
        if (created and created < newest) or (pipelines and m.get("pipeline_tag") not in pipelines):
            continue
        license_ = next((t[8:] for t in m.get("tags", []) if t.startswith("license:")), "?")
        items.append({"title": m["id"], "url": f"https://huggingface.co/{m['id']}", "published": m.get("createdAt"),
                      "text": f"Trending on Hugging Face. Likes {m.get('likes', 0)}, downloads {m.get('downloads', 0)}, "
                              f"type {m.get('pipeline_tag')}, license {license_}, created {(m.get('createdAt') or '?')[:10]}."})
    return items


FETCHERS = {"rss": fetch_rss, "hn": fetch_hn, "github_trending": fetch_github_trending,
            "github_new": fetch_github_new, "hf_models": fetch_hf_models}
