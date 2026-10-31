"""Make each pin's image with Raywake and write a local preview. Claude Code reviews the images."""
from __future__ import annotations

import html
from pathlib import Path

from .raywake import CREDITS_PER_USD, RaywakeClient


def prompt_for(pin: dict, with_product: bool) -> str:
    parts = []
    if with_product:
        parts.append("Keep the product from the reference image exactly as it is: same shape, colors, "
                     "labels and design. Place it in this scene:")
    parts.append(pin["scene"].rstrip(".") + ".")
    parts.append("Vertical 2:3 Pinterest pin, editorial photography quality, natural light, uncluttered.")
    if pin.get("overlay"):
        parts.append(f'Add the headline "{pin["overlay"]}" in large, clean, highly legible type in the upper third, '
                     "on a calm area of the image. Write nothing else anywhere.")
    else:
        parts.append("No text, letters, logos or watermarks anywhere.")
    return " ".join(parts)


def estimate(plan: dict, references: list[str] | None, client: RaywakeClient, redo: set[int] = frozenset()) -> float:
    """Credits for the pins render would make, from one free quote."""
    todo = pending(plan, redo)
    if not todo:
        return 0.0
    quote = client.quote(prompt_for(todo[0], bool(references) and not client.model), references)
    return float(quote.get("credits") or 0) * len(todo)


def pending(plan: dict, redo: set[int] = frozenset()) -> list[dict]:
    """Pins to (re)make: without an image, or named in redo by number."""
    return [pin for index, pin in enumerate(plan["pins"], 1)
            if not pin.get("post_id") and (index in redo or not pin.get("image"))]


def render(plan: dict, folder: Path, references: list[str] | None, client: RaywakeClient,
           redo: set[int] = frozenset(), log=print) -> float:
    """Generate the pending pins; returns credits spent in this run."""
    spent = 0.0
    for index, pin in enumerate(plan["pins"], 1):
        if pin not in pending(plan, redo):
            continue
        with_product = bool(references) and not client.model
        image, credits = client.generate(prompt_for(pin, with_product), references)
        path = folder / f"pin-{index:02d}.jpg"
        path.write_bytes(image)
        spent += credits
        pin.update(image=path.name, credits=round((pin.get("credits") or 0) + credits, 2))
        log(f"  pin {index}: {path} (${credits / CREDITS_PER_USD:.2f})")
    return spent


def preview(plan: dict, folder: Path) -> Path:
    cards = []
    for pin in plan["pins"]:
        image = f'<img src="{html.escape(pin["image"])}" alt="">' if pin.get("image") else "<div class=empty>no image</div>"
        problems = "".join(f"<p class=warn>{html.escape(p)}</p>" for p in pin.get("problems") or [])
        cards.append(f"""<article>{image}<h2>{html.escape(pin['title'])}</h2><p>{html.escape(pin['description'])}</p>
<dl><dt>Keyword</dt><dd>{html.escape(pin['keyword'])}</dd><dt>Board</dt><dd>{html.escape(pin['board'])}</dd>
<dt>Cost</dt><dd>${(pin.get('credits') or 0) / CREDITS_PER_USD:.2f}</dd></dl>{problems}</article>""")
    total = sum(pin.get("credits") or 0 for pin in plan["pins"]) / CREDITS_PER_USD
    page = f"""<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pins for {html.escape(plan['title'])}</title>
<style>body{{font:14px/1.5 system-ui,sans-serif;margin:24px;background:#f6f5f2;color:#222}}
main{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:20px}}
article{{background:#fff;border-radius:16px;padding:12px}}img{{width:100%;border-radius:12px;aspect-ratio:2/3;object-fit:cover}}
h2{{font-size:15px;margin:10px 0 4px}}dl{{display:grid;grid-template-columns:auto 1fr;gap:2px 8px;font-size:12px;color:#555}}
dd{{margin:0}}.warn{{color:#b42318;font-size:12px}}.empty{{aspect-ratio:2/3;background:#eee;border-radius:12px}}</style>
<h1>{html.escape(plan['title'])}</h1><p>Links to <a href="{html.escape(plan['url'])}">{html.escape(plan['url'])}</a>
 · images ${total:.2f}</p><main>{''.join(cards)}</main>"""
    path = folder / "preview.html"
    path.write_text(page)
    return path
