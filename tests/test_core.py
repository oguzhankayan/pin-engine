from datetime import datetime

from pin_engine import page, plan, publish, render
from pin_engine.raywake import image_size

HTML = """<html><head><title>Fallback</title>
<meta property="og:title" content="Teacher Appreciation Printable Cards">
<meta property="og:site_name" content="Paper Hare">
<meta name="description" content="Set of 12 printable thank-you cards.">
<meta property="og:image" content="/img/cards.jpg">
<script type="application/ld+json">{"@context":"https://schema.org","@type":"Product","name":"Cards",
 "image":["https://cdn.example.com/a.jpg"],"offers":{"price":"4.50","priceCurrency":"USD"}}</script>
<script>var x = "not text";</script></head><body><nav>Menu</nav><h1>Cards</h1><p>Print at home.</p></body></html>"""


def test_page_reads_meta_product_and_visible_text():
    result = page.parse("https://shop.example.com/listing/1", HTML)
    assert result.title == "Teacher Appreciation Printable Cards" and result.site == "Paper Hare"
    assert result.price == "4.50 USD"
    assert result.images == ["https://shop.example.com/img/cards.jpg", "https://cdn.example.com/a.jpg"]
    assert "Print at home." in result.text and "not text" not in result.text and "Menu" not in result.text


def test_plan_problems_catch_limits_dashes_and_empty_fields():
    good = {"title": "Teacher gift ideas", "description": "Twelve cards.", "overlay": "12 cards", "scene": "A desk."}
    assert plan.problems(good) == []
    bad = {**good, "title": "x" * 101, "overlay": "y" * 61, "description": "a — b", "scene": ""}
    assert len(plan.problems(bad)) == 4


def test_prompt_keeps_the_reference_product_and_controls_text():
    pin = {"scene": "On a wooden desk at golden hour", "overlay": "Teacher Gift Ideas"}
    prompt = render.prompt_for(pin, with_product=True)
    assert prompt.startswith("Keep the product from the reference image exactly") and '"Teacher Gift Ideas"' in prompt
    assert "No text" in render.prompt_for({**pin, "overlay": ""}, with_product=False)


def test_slots_space_pins_from_tomorrow_evening():
    start = publish.default_start(datetime(2026, 10, 31, 15, 30))
    assert publish.slots(3, start, 24) == ["2026-11-01T20:00:00", "2026-11-02T20:00:00", "2026-11-03T20:00:00"]


def test_boards_match_by_name_ignoring_case():
    found = publish.match_boards(["Teacher Gift Ideas", "Classroom Decor"], [{"id": "1", "name": "teacher gift ideas "}])
    assert found == {"Teacher Gift Ideas": "1", "Classroom Decor": None}


def test_metrics_prefer_the_pinterest_platform_numbers():
    response = {"analytics": {"impressions": 1}, "platformAnalytics": [
        {"platform": "pinterest", "analytics": {"impressions": 120, "saves": 7, "clicks": 3}}]}
    assert publish.metrics(response) == {"impressions": 120, "saves": 7, "clicks": 3}


def test_image_size():
    assert image_size("1024x1536") == {"width": 1024, "height": 1536}
