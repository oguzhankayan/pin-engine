"""Schedule rendered pins on Pinterest through Zernio, and read back how they did."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import DATA_DIR
from .zernio import ZernioClient, ZernioError

LEDGER = DATA_DIR / "ledger.jsonl"


def slots(count: int, start: datetime, every_hours: float) -> list[str]:
    """Local times for each pin, one per interval: a steady cadence reads as a person, not a bot."""
    return [(start + timedelta(hours=every_hours * index)).strftime("%Y-%m-%dT%H:%M:%S") for index in range(count)]


def default_start(now: datetime | None = None, hour: int = 20) -> datetime:
    """Tomorrow's evening slot, when Pinterest use peaks."""
    now = now or datetime.now()
    return (now + timedelta(days=1)).replace(hour=hour, minute=0, second=0, microsecond=0)


def match_boards(names: list[str], boards: list[dict]) -> dict[str, str | None]:
    existing = {board["name"].strip().lower(): board["id"] for board in boards}
    return {name: existing.get(name.strip().lower()) for name in names}


def queue(plan: dict) -> list[dict]:
    """Pins that have an image and are not published yet."""
    return [pin for pin in plan["pins"] if pin.get("image") and not pin.get("post_id") and not pin.get("problems")]


def publish(plan: dict, folder: Path, client: ZernioClient, account: dict, board_ids: dict[str, str],
            times: list[str], draft: bool = False, log=print) -> int:
    published = 0
    for pin, when in zip(queue(plan), times):
        entry = {"url": plan["url"], "angle": pin["angle"], "keyword": pin["keyword"], "title": pin["title"]}
        try:
            media = client.upload(folder / pin["image"])
            post = client.create_pin(account_id=account["_id"], board_id=board_ids[pin["board"]], title=pin["title"],
                                     description=pin["description"], link=plan["url"], media_url=media,
                                     scheduled_for=None if draft else when, draft=draft)
            pin.update(post_id=post.get("_id"), scheduled_for=post.get("scheduledFor") or when, status=post.get("status"))
            entry.update(post_id=pin["post_id"], scheduled_for=pin["scheduled_for"], status=pin["status"])
            published += 1
            log(f"  {pin['status'] or 'created'} {when}  {pin['title'][:60]}")
        except (ZernioError, KeyError, OSError) as error:  # one bad pin must not stop the batch
            entry.update(status="error", error=str(error)[:400])
            log(f"  error: {pin['title'][:50]}: {str(error)[:160]}")
        record(entry)
    return published


def record(entry: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as handle:
        handle.write(json.dumps({"recorded_at": datetime.now().isoformat(timespec="seconds"), **entry}, ensure_ascii=False) + "\n")


def ledger() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]


def metrics(response: dict) -> dict:
    """Pinterest's numbers from Zernio's single-post analytics (impressions, saves, clicks)."""
    found = response.get("analytics") or {}
    for item in response.get("platformAnalytics") or []:
        if item.get("platform") == "pinterest" and item.get("analytics"):
            found = item["analytics"]
    return {key: int(found.get(key) or 0) for key in ("impressions", "saves", "clicks")}


def stats(client: ZernioClient) -> list[dict]:
    rows = []
    for entry in ledger():
        if not entry.get("post_id"):
            continue
        try:
            numbers = metrics(client.post_analytics(entry["post_id"]))
        except ZernioError:
            numbers = {"impressions": 0, "saves": 0, "clicks": 0}
        rows.append({**entry, **numbers})
        time.sleep(0.2)
    return sorted(rows, key=lambda row: (row["saves"], row["clicks"], row["impressions"]), reverse=True)
