"""Rendering. Jobs build a channel-neutral `doc`:

    {"title", "subtitle", "color", "summary", "blocks": [{"kind": "md"|"hr"|"fold", "text", "title"}]}

Block text is markdown with **bold**, [links](url), "- " lists and <font color='grey'>muted</font> spans
(Feishu's dialect); each renderer translates that to its target: Feishu card JSON 2.0, Markdown, HTML,
Slack mrkdwn, plain text.
"""
import html
import re

from . import tracking
from .util import days_between, link_text, stars

UI = {
    "en": {
        "news_title": "AI Daily", "papers_title": "Agent Papers", "headline": "Today",
        "for_profile": "{icon} For {label}", "followups": "🔁 Follow-ups", "oss": "🧩 Open source",
        "tiers": {5: "🔥 Must read", 4: "👍 Recommended", 3: "👀 Worth a look"},
        "manual": "watching", "day_n": "day {n}", "new": "New: ",
        "news_subtitle": "{news} news · {must} must-read · {oss} open source",
        "followup_subtitle": " · {n} follow-ups",
        "news_footer": "{sources} sources · {candidates} candidates · tracking {topics} topics · 3★+ only · "
                       "AI-generated, check the originals",
        "trend": "Trend", "details": "Details", "problem": "Problem", "method": "Method", "results": "Results",
        "limitations": "Limitations", "affected": "Affected", "action": "Action", "code": "Code",
        "original": "Original title", "basis": "Based on", "fulltext": "full text",
        "abstract_only": "abstract only (no HTML full text)", "tracking": "🔁 Tracking: {name}",
        "rechecked": "📈 Re-evaluated after gaining attention", "glance": "📌 At a glance",
        "papers_subtitle": "{read} deep reads · {glance} at a glance",
        "papers_footer": "{n} new papers · {read} read in full · interpreted by AI from the full text, check the original",
        "actions": {"try": "try it", "watch": "watch", "fyi": "FYI"},
        "failure": "Argus: the {job} job failed", "test": "Argus test message — delivery works.",
    },
    "zh": {
        "news_title": "AI 日报", "papers_title": "Agent 论文精读", "headline": "今日要点",
        "for_profile": "{icon} 对 {label}", "followups": "🔁 追踪更新", "oss": "🧩 开源项目",
        "tiers": {5: "🔥 必读", 4: "👍 推荐", 3: "👀 值得一看"},
        "manual": "手动关注", "day_n": "追踪第 {n} 天", "new": "新进展：",
        "news_subtitle": "新闻 {news} 条 · 必读 {must} 条 · 开源项目 {oss} 个",
        "followup_subtitle": " · 追踪更新 {n} 条",
        "news_footer": "{sources} 个来源 · {candidates} 条候选 · 追踪中 {topics} 个主题 · 仅推送 3 星及以上 · "
                       "由 AI 生成，细节以原文为准",
        "trend": "今日趋势", "details": "详细解读", "problem": "问题", "method": "方法", "results": "结果",
        "limitations": "局限", "affected": "相关模块", "action": "建议", "code": "代码",
        "original": "原题", "basis": "依据", "fulltext": "全文", "abstract_only": "仅摘要（未取到 HTML 全文）",
        "tracking": "🔁 追踪：{name}", "rechecked": "📈 热度上升后重新评估", "glance": "📌 速览",
        "papers_subtitle": "精读 {read} 篇 · 速览 {glance} 篇",
        "papers_footer": "{n} 篇新论文 · 精读 {read} 篇 · AI 阅读全文后生成，结论以原文为准",
        "actions": {"try": "建议实验", "watch": "持续观察", "fyi": "了解即可"},
        "failure": "Argus：{job} 任务运行失败", "test": "Argus 测试消息：推送渠道工作正常。",
    },
}


def ui(cfg):
    return UI.get(cfg["language"]["ui"], UI["en"])


def grey(s):
    return f"<font color='grey'>{s}</font>"


# ---------------------------------------------------------------- news

def _entry(i, note_icon):
    s = f"{stars(i['stars'])}　**[{link_text(i['title'])}]({i['url']})**\n{i['summary']}"
    if i.get("profile_note"):
        s += f"\n{note_icon} {i['profile_note']}"
    return s + f"　{grey(i['source'])}"


def news_doc(cfg, digest):
    t, prof = ui(cfg), cfg["profile"]
    head = f"**{t['headline']}**　{digest['overview']}"
    if digest.get("profile_takeaway"):
        head += f"\n**{t['for_profile'].format(icon=prof['icon'], label=prof['label'])}**　{digest['profile_takeaway']}"
    blocks = [{"kind": "md", "text": head}]

    if digest.get("followups"):
        by_id = {x["id"]: x for x in tracking.topics(cfg)}
        lines = [f"**{t['followups']}**"]
        for f in digest["followups"]:
            topic = by_id.get(f["followup_of"], {"name": f["title"], "kind": "auto", "created": digest["date"]})
            since = t["manual"] if topic["kind"] == "manual" else t["day_n"].format(n=days_between(topic["created"], digest["date"]))
            entry = (f"{stars(f['stars'])}　**[{link_text(topic['name'])}]({f['url']})**　{grey(since)}\n"
                     f"{t['new']}{f['what_new']}")
            if f.get("profile_note"):
                entry += f"\n{prof['icon']} {f['profile_note']}"
            lines.append(entry)
        blocks += [{"kind": "hr"}, {"kind": "md", "text": "\n\n".join(lines)}]

    news = [i for i in digest["items"] if i["category"] != "open_source"]
    oss = [i for i in digest["items"] if i["category"] == "open_source"]
    sections = [(label, [i for i in news if i["stars"] == tier]) for tier, label in t["tiers"].items()]
    for label, items in sections + [(t["oss"], oss)]:
        if items:
            text = "\n\n".join([f"**{label}**"] + [_entry(i, prof["icon"]) for i in items])
            blocks += [{"kind": "hr"}, {"kind": "md", "text": text}]
    blocks.append({"kind": "md", "small": True, "text": grey(t["news_footer"].format(
        sources=digest["source_count"], candidates=digest["candidate_count"], topics=len(tracking.active(cfg))))})

    subtitle = t["news_subtitle"].format(news=len(news), must=sum(i["stars"] == 5 for i in news), oss=len(oss))
    if digest.get("followups"):
        subtitle += t["followup_subtitle"].format(n=len(digest["followups"]))
    title = f"{t['news_title']} · {digest['date']}"
    top = digest["items"][0]["title"] if digest["items"] else ""
    return {"title": title, "subtitle": subtitle, "color": "indigo", "summary": f"{title}: {top}", "blocks": blocks}


# ---------------------------------------------------------------- papers

def papers_doc(cfg, report):
    t, prof = ui(cfg), cfg["profile"]
    names = {x["id"]: x["name"] for x in tracking.topics(cfg)}
    blocks = [{"kind": "md", "text": f"**{t['trend']}**　{report['trend']}"}]
    for p in report["papers"]:
        r = p["relevance"]
        tags = []
        if p.get("topic_id") in names:
            tags.append(t["tracking"].format(name=names[p["topic_id"]]))
        if p.get("rechecked"):
            tags.append(t["rechecked"])
        tag_line = grey(" · ".join(tags)) + "\n" if tags else ""
        basis = t["fulltext"] if p["basis"] == "full_text" else t["abstract_only"]
        upvotes = f" · HF 👍 {p['hf_upvotes']}" if p.get("hf_upvotes") else ""
        blocks += [
            {"kind": "hr"},
            {"kind": "md", "text": f"{stars(p['stars'])}　**[{link_text(p['title_local'])}]({p['url']})**\n"
                                   f"{tag_line}{p['one_liner']}\n{prof['icon']} {p['profile_brief']}"},
            {"kind": "fold", "title": t["details"], "text":
                f"**{t['problem']}**　{p['problem']}\n\n**{t['method']}**　{p['method']}\n\n"
                f"**{t['results']}**　{p['results']}\n\n**{t['limitations']}**　{p['limitations']}\n\n"
                f"**{t['for_profile'].format(icon=prof['icon'], label=prof['label'])}**　{r['insight']}\n"
                + grey(f"{t['affected']}: {', '.join(r['modules']) or '—'} · {t['action']}: "
                       f"{t['actions'].get(r['action'], r['action'])}")
                + f"\n\n**{t['code']}**　{p['code']}\n"
                + grey(f"{t['original']}: {link_text(p['title'])} · {t['basis']}: {basis}{upvotes}")},
        ]
    if report["glance"]:
        lines = [f"- [{link_text(g['title_local'])}](https://arxiv.org/abs/{g['id']})　{g['one_liner']}"
                 for g in report["glance"]]
        blocks += [{"kind": "hr"}, {"kind": "md", "text": f"**{t['glance']}**\n" + "\n".join(lines)}]
    blocks.append({"kind": "md", "small": True, "text": grey(t["papers_footer"].format(
        n=report["candidate_count"], read=len(report["papers"])))})
    title = f"{t['papers_title']} · {report['date']}"
    first = report["papers"][0]["title_local"] if report["papers"] else ""
    return {"title": title, "subtitle": t["papers_subtitle"].format(read=len(report["papers"]), glance=len(report["glance"])),
            "color": "turquoise", "summary": f"{title}: {first}", "blocks": blocks}


# ---------------------------------------------------------------- renderers

FONT = re.compile(r"<font color='(\w+)'>(.*?)</font>", re.S)
LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)


def feishu_card(doc):
    elements = []
    for b in doc["blocks"]:
        if b["kind"] == "hr":
            elements.append({"tag": "hr"})
        elif b["kind"] == "fold":
            elements.append({"tag": "collapsible_panel", "expanded": False,
                             "header": {"title": {"tag": "markdown", "content": grey(b["title"])}},
                             "elements": [{"tag": "markdown", "content": b["text"]}]})
        else:
            el = {"tag": "markdown", "content": b["text"]}
            if b.get("small"):
                el["text_size"] = "notation"
            elements.append(el)
    return {
        "schema": "2.0",
        "config": {"summary": {"content": doc["summary"]}},
        "header": {"title": {"tag": "plain_text", "content": doc["title"]},
                   "subtitle": {"tag": "plain_text", "content": doc["subtitle"]}, "template": doc["color"]},
        "body": {"direction": "vertical", "elements": elements},
    }


def markdown(doc):
    out = [f"# {doc['title']}", f"*{doc['subtitle']}*", ""]
    for b in doc["blocks"]:
        if b["kind"] == "hr":
            out += ["---", ""]
        elif b["kind"] == "fold":
            out += [f"<details><summary>{b['title']}</summary>", "", FONT.sub(r"*\2*", b["text"]), "", "</details>", ""]
        else:
            out += [FONT.sub(r"*\2*", b["text"]), ""]
    return "\n".join(out).replace("　", " ")


def _md_html(text):
    marks = {}

    def keep(s):
        marks[f"\x00{len(marks)}\x00"] = s
        return f"\x00{len(marks) - 1}\x00"

    text = FONT.sub(lambda m: keep("<span class='muted'>") + m.group(2) + keep("</span>"), text)
    text = html.escape(text, quote=False)
    text = LINK.sub(lambda m: f"<a href=\"{html.escape(m.group(2))}\">{m.group(1)}</a>", text)
    text = BOLD.sub(r"<strong>\1</strong>", text)
    lines, out, in_list = text.split("\n"), [], False
    for line in lines:
        if line.startswith("- "):
            out.append(("" if in_list else "<ul>") + f"<li>{line[2:]}</li>")
            in_list = True
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(line + "<br>" if line else "<br>")
    if in_list:
        out.append("</ul>")
    text = "\n".join(out)
    for k, v in marks.items():
        text = text.replace(k, v)
    return text


def html_page(doc):
    parts = []
    for b in doc["blocks"]:
        if b["kind"] == "hr":
            parts.append("<hr>")
        elif b["kind"] == "fold":
            parts.append(f"<details><summary>{html.escape(b['title'])}</summary><div>{_md_html(b['text'])}</div></details>")
        else:
            parts.append(f"<div class='{'small' if b.get('small') else 'block'}'>{_md_html(b['text'])}</div>")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(doc['title'])}</title>
<style>
:root{{--bg:#fff;--fg:#1f2328;--muted:#6e7781;--line:#d0d7de;--link:#0969da}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--fg:#e6edf3;--muted:#8d96a0;--line:#30363d;--link:#4493f8}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
max-width:760px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;margin:0}} .sub{{color:var(--muted);margin-bottom:16px}} a{{color:var(--link)}}
.muted{{color:var(--muted)}} .small{{color:var(--muted);font-size:13px}} hr{{border:0;border-top:1px solid var(--line);margin:16px 0}}
details{{margin:4px 0 8px}} summary{{color:var(--muted);cursor:pointer}} ul{{padding-left:20px;margin:4px 0}}
</style></head><body>
<h1>{html.escape(doc['title'])}</h1><div class="sub">{html.escape(doc['subtitle'])}</div>
{''.join(parts)}
</body></html>
"""


def plain(doc, include_folds=False):
    """Markdown without Feishu font tags; folds dropped unless asked (chat messages stay short)."""
    out = [f"**{doc['title']}** — {doc['subtitle']}", ""]
    for b in doc["blocks"]:
        if b["kind"] == "hr":
            out.append("")
        elif b["kind"] != "fold" or include_folds:
            out += [FONT.sub(r"\2", b["text"]), ""]
    return "\n".join(out).replace("　", " ").strip()


def slack(doc):
    text = plain(doc)
    text = LINK.sub(lambda m: f"<{m.group(2)}|{m.group(1)}>", text)
    return BOLD.sub(r"*\1*", text)
