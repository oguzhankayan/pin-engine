"""render → preview → publish → stats through the CLI, with Raywake and Zernio replaced by fakes."""
import io
import json

import pytest
from click.testing import CliRunner
from PIL import Image

import pin_engine.__main__ as cli
import pin_engine.publish as publishing
import pin_engine.zernio as zernio

PIN = {"angle": "travel", "keyword": "travel shoes", "title": "Travel shoes that breathe",
       "description": "Light and washable.", "overlay": "Travel shoes", "scene": "A cobblestone street.",
       "board": "Travel Shoes"}


def jpeg(color="black") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 60), color).save(buffer, "JPEG")
    return buffer.getvalue()


class FakeRaywake:
    prompts: list = []

    def quote(self, prompt, references=None):
        return {"quote_id": "q", "credits": 32}

    def generate(self, prompt, references=None):
        FakeRaywake.prompts.append((prompt, references))
        return jpeg("white"), 30.0


class FakeZernio:
    posts: list = []
    boards_made: list = []

    def account(self, account_id=None):
        return {"_id": "acc-1", "username": "shop"}

    def boards(self, account_id):
        return [{"id": "b-travel", "name": "travel shoes"}]

    def create_board(self, account_id, name):
        FakeZernio.boards_made.append(name)
        return {"id": "b-" + name.split()[0].lower()}

    def upload(self, path):
        return "https://media.zernio.example/" + path.name

    def create_pin(self, **kwargs):
        FakeZernio.posts.append(kwargs)
        return {"_id": f"post-{len(FakeZernio.posts)}", "status": "scheduled", "scheduledFor": kwargs["scheduled_for"]}

    def post_analytics(self, post_id):
        saves = {"post-1": 2, "post-2": 9}[post_id]
        return {"platformAnalytics": [{"platform": "pinterest", "analytics": {"impressions": 100, "saves": saves, "clicks": 1}}]}


@pytest.fixture
def project(tmp_path, monkeypatch):
    folder = tmp_path / "output" / "2026-11-01-tree-runner"
    folder.mkdir(parents=True)
    (folder / "product.jpg").write_bytes(jpeg())
    plan = {"url": "https://shop.example.com/p/tree-runner", "site": "shop", "title": "Tree Runner", "language": "English",
            "created_at": "2026-11-01T10:00:00", "product_photo": True, "page": {},
            "pins": [PIN, {**PIN, "keyword": "washable sneakers", "board": "Laundry Tips", "overlay": ""}]}
    (folder / "plan.json").write_text(json.dumps(plan))
    monkeypatch.setattr(cli, "RaywakeClient", FakeRaywake)
    monkeypatch.setattr(zernio, "ZernioClient", FakeZernio)
    monkeypatch.setattr(publishing, "LEDGER", tmp_path / "data" / "ledger.jsonl")
    FakeRaywake.prompts, FakeZernio.posts, FakeZernio.boards_made = [], [], []
    return folder


def test_render_makes_every_pin_from_the_product_photo_and_writes_a_preview(project):
    result = CliRunner().invoke(cli.cli, ["render", str(project), "--yes"])
    assert result.exit_code == 0, result.output
    plan = json.loads((project / "plan.json").read_text())
    assert [pin["image"] for pin in plan["pins"]] == ["pin-01.jpg", "pin-02.jpg"]
    assert all((project / pin["image"]).exists() and pin["credits"] == 30 for pin in plan["pins"])
    prompt, references = FakeRaywake.prompts[0]
    assert prompt.startswith("Keep the product from the reference image") and references[0].startswith("data:image/jpeg")
    assert "No text" in FakeRaywake.prompts[1][0]
    preview = (project / "preview.html").read_text()
    assert "Travel shoes that breathe" in preview and "images $0.60" in preview
    again = CliRunner().invoke(cli.cli, ["render", str(project), "--redo", "2", "--yes"])
    assert again.exit_code == 0 and len(FakeRaywake.prompts) == 3
    assert json.loads((project / "plan.json").read_text())["pins"][1]["credits"] == 60


def test_render_refuses_an_unfinished_plan(project):
    plan = json.loads((project / "plan.json").read_text())
    plan["pins"][1]["title"] = ""
    (project / "plan.json").write_text(json.dumps(plan))
    result = CliRunner().invoke(cli.cli, ["render", str(project), "--yes"])
    assert result.exit_code != 0 and "title is empty" in result.output and not FakeRaywake.prompts


def test_publish_asks_then_schedules_one_pin_a_day_on_matching_boards(project):
    CliRunner().invoke(cli.cli, ["render", str(project), "--yes"])
    declined = CliRunner().invoke(cli.cli, ["publish", str(project), "--create-boards", "--start", "2026-11-02 20:00"], input="n\n")
    assert declined.exit_code == 0 and not FakeZernio.posts
    result = CliRunner().invoke(cli.cli, ["publish", str(project), "--create-boards", "--start", "2026-11-02 20:00", "--yes"])
    assert result.exit_code == 0, result.output
    first, second = FakeZernio.posts
    assert (first["board_id"], first["scheduled_for"]) == ("b-travel", "2026-11-02T20:00:00")
    assert (second["board_id"], second["scheduled_for"]) == ("b-laundry", "2026-11-03T20:00:00")
    assert FakeZernio.boards_made == ["Laundry Tips"]
    assert first["link"] == "https://shop.example.com/p/tree-runner" and first["media_url"].endswith("pin-01.jpg")
    plan = json.loads((project / "plan.json").read_text())
    assert [pin["post_id"] for pin in plan["pins"]] == ["post-1", "post-2"]
    # Already scheduled pins are never sent twice.
    assert "Nothing to publish" in CliRunner().invoke(cli.cli, ["publish", str(project), "--yes"]).output
    stats = CliRunner().invoke(cli.cli, ["stats"])
    assert stats.exit_code == 0 and stats.output.index("washable") < stats.output.index("travel shoes")


def test_zernio_pin_payload_marks_ai_and_uses_board_link_and_schedule(monkeypatch):
    sent = {}
    client = zernio.ZernioClient.__new__(zernio.ZernioClient)
    monkeypatch.setattr(client, "_request", lambda method, path, **kw: sent.update(kw["body"]) or {"post": {"_id": "p"}}, raising=False)
    client.create_pin(account_id="a", board_id="b", title="T", description="D", link="https://x.example",
                      media_url="https://m.example/1.jpg", scheduled_for="2026-11-02T20:00:00")
    data = sent["platforms"][0]["platformSpecificData"]
    assert data == {"boardId": "b", "title": "T", "link": "https://x.example", "isAiGenerated": True}
    assert sent["content"] == "D" and sent["scheduledFor"] == "2026-11-02T20:00:00" and "publishNow" not in sent
