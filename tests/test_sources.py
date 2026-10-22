import unittest
from datetime import datetime, timezone

from argus import sources
from tests.helpers import FIXTURES

SINCE = datetime(2026, 10, 20, tzinfo=timezone.utc)


class FeedTests(unittest.TestCase):
    def test_rss_window_and_html_cleanup(self):
        items = sources.parse_feed((FIXTURES / "feed_rss.xml").read_bytes(), {}, SINCE)
        self.assertEqual([i["url"] for i in items], ["https://example.com/new", "https://example.com/garden"])
        self.assertEqual(items[0]["text"], "An agent framework with MCP support.")

    def test_keyword_filter_and_ignore_window(self):
        items = sources.parse_feed((FIXTURES / "feed_rss.xml").read_bytes(),
                                   {"keyword_filter": True, "ignore_window": True}, SINCE)
        self.assertEqual([i["url"] for i in items], ["https://example.com/new", "https://example.com/old"])

    def test_atom_alternate_link(self):
        items = sources.parse_feed((FIXTURES / "feed_atom.xml").read_bytes(), {}, SINCE)
        self.assertEqual(items[0]["url"], "https://example.com/v2")
        self.assertTrue(items[0]["published"].startswith("2026-10-21"))


class TrendingTests(unittest.TestCase):
    def test_parse_and_filter(self):
        page = (FIXTURES / "github_trending.html").read_text()
        everything = sources.parse_github_trending(page, {})
        self.assertEqual({i["url"] for i in everything},
                         {"https://github.com/cloudflare/security-audit-skill", "https://github.com/strelov1/freehire"})
        ai_only = sources.parse_github_trending(page, {"keyword_filter": True})
        self.assertEqual([i["url"] for i in ai_only], ["https://github.com/cloudflare/security-audit-skill"])
        self.assertIn("today", ai_only[0]["text"])


if __name__ == "__main__":
    unittest.main()
