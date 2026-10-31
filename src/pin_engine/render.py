"""Make each pin's image with Raywake, check it with Claude, and write a local preview."""
from __future__ import annotations

import html
from pathlib import Path

from .llm import ask_json, image_block
from .raywake import CREDITS_PER_USD, RaywakeClient

QC_SYSTEM = """You check one generated Pinterest pin image before it is published.
Return ONLY JSON: {"pass": true|false, "issue": "short reason when it fails"}.
Fail when: the requested headline is misspelled, cut off or unreadable; there is any other
written text, watermark or logo; a reference product was supplied and the product in the pin
differs from it (shape, color, label, design); the image is distorted or clearly broken.
Pass otherwise. Be strict about text and product fidelity, lenient about taste."""


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


def check(image: bytes, pin: dict, product: bytes | None) -> dict:
    content = [{"type": "text", "text": "Generated pin:"}, image_block(image)]
    if product:
        content += [{"type": "text", "text": "Reference product photo:"}, image_block(product)]
    content.append({"type": "text", "text": "Requested headline: " + (repr(pin["overlay"]) if pin.get("overlay") else "none (no text allowed)")})
    try:
        verdict = ask_json(QC_SYSTEM, content, kind="qc", max_tokens=2000)
        return {"pass": bool(verdict.get("pass")), "issue": str(verdict.get("issue", ""))[:200]}
    except Exception as error:  # noqa: BLE001 - a failed check must not discard a paid image
        return {"pass": True, "issue": f"check unavailable: {error}"[:200]}


def estimate(plan: dict, references: list[str] | None, client: RaywakeClient) -> float:
    """Credits for the pins that still need an image, from one free quote."""
    todo = [pin for pin in plan["pins"] if not pin.get("image")]
    if not todo:
        return 0.0
    quote = client.quote(prompt_for(todo[0], bool(references)), references)
    return float(quote.get("credits") or 0) * len(todo)


def render(plan: dict, folder: Path, product: bytes | None, references: list[str] | None,
           client: RaywakeClient, rerolls: int = 1, qc: bool = True, log=print) -> None:
    for index, pin in enumerate(plan["pins"], 1):
        if pin.get("image") or pin.get("problems"):
            continue
        prompt = prompt_for(pin, bool(references))
        spent = 0.0
        for attempt in range(rerolls + 1):
            image, credits = client.generate(prompt, references)
            spent += credits
            path = folder / f"pin-{index:02d}.jpg"
            path.write_bytes(image)
            verdict = check(image, pin, product) if qc else {"pass": True, "issue": ""}
            log(f"  pin {index}: {'ok' if verdict['pass'] else 'retry: ' + verdict['issue']} "
                f"(${credits / CREDITS_PER_USD:.2f})")
            if verdict["pass"] or attempt == rerolls:
                break
        pin.update(image=path.name, credits=round(spent, 2), qc=verdict)


def preview(plan: dict, folder: Path) -> Path:
    cards = []
    for pin in plan["pins"]:
        image = f'<img src="{html.escape(pin["image"])}" alt="">' if pin.get("image") else "<div class=empty>no image</div>"
        flag = "" if (pin.get("qc") or {}).get("pass", True) else f'<p class=warn>Check: {html.escape(pin["qc"]["issue"])}</p>'
        problems = "".join(f"<p class=warn>{html.escape(p)}</p>" for p in pin.get("problems") or [])
        cards.append(f"""<article>{image}<h2>{html.escape(pin['title'])}</h2><p>{html.escape(pin['description'])}</p>
<dl><dt>Keyword</dt><dd>{html.escape(pin['keyword'])}</dd><dt>Board</dt><dd>{html.escape(pin['board'])}</dd>
<dt>Cost</dt><dd>${(pin.get('credits') or 0) / CREDITS_PER_USD:.2f}</dd></dl>{flag}{problems}</article>""")
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
