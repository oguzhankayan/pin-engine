"""The pin plan: one JSON file per link. Claude Code writes the pins; this module checks them."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .config import DESCRIPTION_LIMIT, OUTPUT_DIR, OVERLAY_LIMIT, TITLE_LIMIT
from .page import Page

FIELDS = ("angle", "keyword", "title", "description", "overlay", "scene", "board")


def slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit] or "pins"


def skeleton(page: Page, count: int, language: str) -> dict:
    """A plan with the page facts and empty pins for Claude Code to fill in."""
    return {"url": page.url, "site": page.site, "title": page.title, "language": language,
            "created_at": datetime.now().isoformat(timespec="seconds"), "product_photo": False,
            "page": page.brief(), "pins": [dict.fromkeys(FIELDS, "") for _ in range(count)]}


def problems(pin: dict) -> list[str]:
    """Empty when the pin can be rendered and published."""
    found = []
    title, description, overlay = (str(pin.get(k) or "") for k in ("title", "description", "overlay"))
    for field in ("keyword", "title", "description", "scene", "board"):
        if not str(pin.get(field) or "").strip():
            found.append(f"{field} is empty")
    if len(title) > TITLE_LIMIT:
        found.append(f"title is {len(title)} characters (limit {TITLE_LIMIT})")
    if len(description) > DESCRIPTION_LIMIT:
        found.append(f"description is {len(description)} characters (limit {DESCRIPTION_LIMIT})")
    if len(overlay) > OVERLAY_LIMIT:
        found.append(f"overlay is {len(overlay)} characters (limit {OVERLAY_LIMIT})")
    if any(dash in title + description + overlay for dash in "—–"):
        found.append("contains an em or en dash")
    return found


def review(plan: dict) -> dict[int, list[str]]:
    """Problems by pin number, plus repeated keywords (every pin needs its own search)."""
    found = {index: problems(pin) for index, pin in enumerate(plan["pins"], 1)}
    seen: dict[str, int] = {}
    for index, pin in enumerate(plan["pins"], 1):
        keyword = str(pin.get("keyword") or "").strip().lower()
        if keyword and keyword in seen:
            found[index].append(f"same keyword as pin {seen[keyword]}")
        seen.setdefault(keyword, index)
    return {index: issues for index, issues in found.items() if issues}


def folder(plan: dict) -> Path:
    return OUTPUT_DIR / f"{plan['created_at'][:10]}-{slug(plan['title'] or plan['site'])}"


def save(plan: dict, path: Path | None = None) -> Path:
    path = path or folder(plan) / "plan.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    return path


def load(path: str | Path) -> tuple[dict, Path]:
    path = Path(path)
    path = path / "plan.json" if path.is_dir() else path
    return json.loads(path.read_text()), path
