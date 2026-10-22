import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from radar import deliver, news, render, tracking
from tests.helpers import FakeLLM, item, make_cfg

CANDIDATES = [
    {"title": "A", "url": "https://example.com/a", "source": "S1", "text": "", "published": None},
    {"title": "B", "url": "https://example.com/b", "source": "S2", "text": "", "published": None},
    {"title": "Repo", "url": "https://github.com/x/y", "source": "GitHub", "text": "", "open_source": True},
]


def digest_response(**extra):
    resp = {
        "overview": "Today", "profile_takeaway": "Note",
        "items": [item(url="https://example.com/a", stars=5, track_topic="Topic A"),
                  item(url="https://example.com/b", stars=2),                  # below 3 stars: dropped
                  item(url="https://invented.example/x", stars=5)],            # not a candidate: dropped
        "oss_items": [item(url="https://github.com/x/y", stars=4, category="agent_engineering")],
        "topic_updates": [],
    }
    resp.update(extra)
    return resp


class SummarizeTests(unittest.TestCase):
    def test_filters_and_merges(self):
        cfg = make_cfg()
        d = news.summarize(cfg, FakeLLM({"news": digest_response()}), CANDIDATES, "2026-10-22")
        self.assertEqual([i["url"] for i in d["items"]], ["https://example.com/a", "https://github.com/x/y"])
        self.assertEqual(d["items"][1]["category"], "open_source")  # oss_items are forced into open_source
        self.assertEqual(d["followups"], [])

    def test_followups_need_a_real_topic(self):
        cfg = make_cfg()
        topic = tracking.add(cfg, "Topic A", "known", "manual", "2026-10-20")
        resp = digest_response(items=[item(url="https://example.com/a", followup_of=topic["id"], what_new="new!"),
                                      item(url="https://example.com/b", followup_of="no-such-topic", what_new="x")],
                               topic_updates=[{"topic_id": topic["id"], "known": "updated"}])
        d = news.summarize(cfg, FakeLLM({"news": resp}), CANDIDATES, "2026-10-22")
        self.assertEqual([f["url"] for f in d["followups"]], ["https://example.com/a"])
        self.assertEqual(d["items"][0]["followup_of"], "")  # unknown topic -> ordinary item

        tracking.apply_news(cfg, d)
        t = tracking.topics(cfg)[0]
        self.assertEqual((t["known"], t["last_update"], len(t["updates"])), ("updated", "2026-10-22", 1))
        self.assertEqual(len(tracking.recent_pushed(cfg)), 3)

    def test_prompt_contains_context_and_watchlist(self):
        cfg = make_cfg()
        tracking.add(cfg, "Watch me", "facts", "manual", "2026-10-20")
        fake = FakeLLM({"news": digest_response()})
        news.summarize(cfg, fake, CANDIDATES, "2026-10-22")
        prompt = fake.prompts[0][1]
        self.assertIn("Components: planner, executor.", prompt)
        self.assertIn("Watch me", prompt)
        self.assertNotIn("${", prompt)


class TrackingTests(unittest.TestCase):
    def test_auto_topics_open_and_expire(self):
        cfg = make_cfg()
        d = {"date": "2026-10-01", "items": [item(stars=4, track_topic="Big launch")], "followups": []}
        tracking.apply_news(cfg, d)
        self.assertEqual([t["name"] for t in tracking.active(cfg)], ["Big launch"])
        tracking.apply_news(cfg, {"date": "2026-11-05", "items": [], "followups": []})  # > 30 days later
        self.assertEqual(tracking.active(cfg), [])
        self.assertEqual(tracking.recent_pushed(cfg), [])  # pushed log keeps only 7 days


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.cfg = make_cfg({"language": {"ui": "zh"}})
        self.digest = news.summarize(self.cfg, FakeLLM({"news": digest_response()}), CANDIDATES, "2026-10-22")

    def test_feishu_card_shape(self):
        card = render.feishu_card(render.news_doc(self.cfg, self.digest))
        self.assertEqual(card["schema"], "2.0")
        text = json.dumps(card, ensure_ascii=False)
        self.assertIn("🔥 必读", text)
        self.assertIn("🧩 开源项目", text)
        self.assertIn("对 Test", text)

    def test_markdown_html_slack(self):
        doc = render.news_doc(self.cfg, self.digest)
        self.assertIn("[T](https://example.com/a)", render.markdown(doc))
        self.assertNotIn("<font", render.markdown(doc))
        self.assertIn('<a href="https://example.com/a">T</a>', render.html_page(doc))
        self.assertIn("<https://example.com/a|T>", render.slack(doc))


class Hook(BaseHTTPRequestHandler):
    received = []

    def do_POST(self):
        Hook.received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"code":0}')

    def log_message(self, *args):
        pass


class DeliveryTests(unittest.TestCase):
    def test_webhook_command_and_file(self):
        server = HTTPServer(("127.0.0.1", 0), Hook)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{server.server_port}/hook"
        cfg = make_cfg({"delivery": [
            {"type": "webhook", "format": "feishu", "url": url, "secret": "s3cret"},
            {"type": "command", "run": "test -s {feishu_card} && echo ok", "expect_output": "ok"},
            {"type": "file", "dir": "site"},
            {"type": "webhook", "url": "${NOT_SET_ANYWHERE}", "enabled": True},
        ]})
        digest = news.summarize(cfg, FakeLLM({"news": digest_response()}), CANDIDATES, "2026-10-22")
        doc = render.news_doc(cfg, digest)
        paths = deliver.write_artifacts(cfg, "news", "2026-10-22", digest, doc)
        errors = deliver.deliver(cfg, doc, paths)
        server.shutdown()

        self.assertEqual(len(errors), 1)                       # the unresolved ${VAR} connector
        self.assertIn("NOT_SET_ANYWHERE", errors[0])
        payload = Hook.received[-1]
        self.assertEqual(payload["msg_type"], "interactive")
        self.assertIn("sign", payload)                         # Feishu signature when a secret is set
        self.assertTrue((cfg.root / "site" / "news-2026-10-22.html").exists())

    def test_all_connectors_failing_raises(self):
        cfg = make_cfg({"delivery": [{"type": "command", "run": "exit 3"}]})
        digest = news.summarize(cfg, FakeLLM({"news": digest_response()}), CANDIDATES, "2026-10-22")
        doc = render.news_doc(cfg, digest)
        paths = deliver.write_artifacts(cfg, "news", "2026-10-22", digest, doc)
        with self.assertRaises(deliver.DeliveryError):
            deliver.deliver(cfg, doc, paths)


if __name__ == "__main__":
    unittest.main()
