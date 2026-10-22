import tempfile
from pathlib import Path

from radar import settings

FIXTURES = Path(__file__).parent / "fixtures"


def make_cfg(overrides=None):
    """A Config rooted in a fresh temp dir (state/out/logs live there), with an example context file."""
    root = Path(tempfile.mkdtemp(prefix="radar-test-"))
    (root / "profiles").mkdir()
    (root / "profiles" / "ctx.md").write_text("# Test project\nComponents: planner, executor.")
    data = settings._merge(settings.DEFAULTS, {"profile": {"label": "Test", "icon": "🏢", "context_file": "profiles/ctx.md"},
                                               "delivery": []})
    data = settings._merge(data, overrides or {})
    return settings.Config(data, root=root)


def item(**kw):
    base = {"stars": 4, "title": "T", "url": "https://example.com/a", "source": "S", "category": "agent_engineering",
            "summary": "Sum", "profile_note": "", "followup_of": "", "what_new": "", "track_topic": ""}
    base.update(kw)
    return base


class FakeLLM:
    """Returns canned responses by schema name and records prompts."""

    resumable = False

    def __init__(self, responses):
        self.responses, self.prompts = responses, []

    def structured(self, task, prompt, schema_name):
        self.prompts.append((task, prompt))
        resp = self.responses[schema_name]
        return (resp(task) if callable(resp) else resp), None
