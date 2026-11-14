"""pin-engine CLI: read → (Claude Code writes the plan) → check → render → publish → stats."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import click
from rich.console import Console
from rich.table import Table

from . import page as pages
from . import plan as plans
from . import publish as publishing
from . import render as rendering
from .config import settings
from .raywake import CREDITS_PER_USD, RaywakeClient, link, reference, total_spend

console = Console()


PRODUCT = "product.jpg"


def _product(folder: Path) -> tuple[bytes | None, list[str] | None]:
    """The saved product photo and its inline reference, when the plan has one."""
    path = folder / PRODUCT
    if not path.exists():
        return None, None
    photo = path.read_bytes()
    return photo, [reference(photo)]


def _read(url: str, count: int, language: str, title: str | None, photo: str | None) -> tuple[dict, Path]:
    try:
        page = pages.read(url)
    except (SystemExit, Exception) as error:  # noqa: BLE001
        if not title:
            raise SystemExit(f"Could not read {url}: {error}. Pass --title (and --photo) to plan without reading it.")
        page = pages.Page(url=url, title=title, site=urlsplit(url).netloc.removeprefix("www."))
    if title:
        page.title = title
    image = Path(photo).expanduser().read_bytes() if photo else pages.photo(page)
    result = plans.skeleton(page, count, language)
    result["product_photo"] = bool(image)
    result["page"]["has_product_photo"] = bool(image)
    path = plans.save(result)
    if image:
        (path.parent / PRODUCT).write_bytes(image)
    return result, path


def _show(plan: dict) -> None:
    table = Table(show_lines=True)
    for column in ("#", "Keyword", "Title", "Overlay", "Board", "Status"):
        table.add_column(column)
    for index, pin in enumerate(plan["pins"], 1):
        status = "; ".join(pin.get("problems") or []) or pin.get("status") or ("image ready" if pin.get("image") else "planned")
        table.add_row(str(index), pin["keyword"], pin["title"], pin["overlay"] or "-", pin["board"], status)
    console.print(table)


@click.group()
def cli() -> None:
    """Pinterest pins from a link, driven by Claude Code. Images by Raywake, publishing by Zernio."""


@cli.command()
@click.argument("url")
@click.option("--count", default=5, show_default=True, help="Pins to plan.")
@click.option("--language", default="English", show_default=True)
@click.option("--title", default=None, help="Product or post title, when the page cannot be read.")
@click.option("--photo", default=None, type=click.Path(exists=True), help="Local product photo to keep in every pin.")
def read(url: str, count: int, language: str, title: str | None, photo: str | None) -> None:
    """Read URL, save its product photo and an empty plan.json for Claude Code to fill in."""
    result, path = _read(url, count, language, title, photo)
    console.print_json(data={**result["page"], "text": result["page"]["text"][:300] + " ... (full text in plan.json)"})
    console.print(f"Product photo: {'saved as ' + str(path.parent / PRODUCT) if result['product_photo'] else 'none found'}")
    console.print(f"Plan to fill in: {path}  ({count} pins; rules in .claude/skills/pin-engine/SKILL.md)")


@cli.command()
@click.argument("folder")
def check(folder: str) -> None:
    """Validate plan.json: limits, empty fields, dashes and repeated keywords."""
    plan, _ = plans.load(folder)
    found = plans.review(plan)
    _show(plan)
    for index, issues in found.items():
        console.print(f"pin {index}: {'; '.join(issues)}")
    if found:
        raise SystemExit(1)
    console.print("Plan is ready to render.")


@cli.command()
@click.argument("folder")
@click.option("--redo", default="", help="Pin numbers to make again, e.g. 2,4.")
@click.option("--model", default=None, help="Raywake model for every pin, e.g. flux/schnell (about $0.02, text only). "
              "Default: GPT Image 2.5 Sunburst, editing your product photo.")
@click.option("--photo-only", is_flag=True, help="Use the product photo itself on every pin; nothing is generated.")
@click.option("--yes", is_flag=True, help="Skip the cost confirmation.")
def render(folder: str, redo: str, model: str | None, photo_only: bool, yes: bool) -> None:
    """Make the pin images with Raywake (asks before spending) and write preview.html.

    A pin whose "image" field already names a file in the folder keeps it: drop in your own photos."""
    plan, path = plans.load(folder)
    found = plans.review(plan)
    if found:
        raise SystemExit("Fix the plan first: " + " | ".join(f"pin {i}: {'; '.join(v)}" for i, v in found.items()))
    again = {int(part) for part in redo.split(",") if part.strip()}
    _, references = _product(path.parent)
    if photo_only:
        if not references:
            raise SystemExit("No product.jpg in this folder; pass --photo to read, or add your own images.")
        for pin in rendering.pending(plan, again):
            pin["image"] = PRODUCT
        plans.save(plan, path)
        console.print(f"Every pin uses {PRODUCT}. Preview: {rendering.preview(plan, path.parent)}")
        return
    client = RaywakeClient(model=model)
    credits = rendering.estimate(plan, references, client, again)
    if not credits:
        console.print("Every pin already has an image. Use --redo to make one again.")
    elif not yes:
        click.confirm(f"{len(rendering.pending(plan, again))} images, about ${credits / CREDITS_PER_USD:.2f}. Continue?", abort=True)
    spent = rendering.render(plan, path.parent, references, client, again, log=console.print)
    plans.save(plan, path)
    preview = rendering.preview(plan, path.parent)
    total = sum(pin.get("credits") or 0 for pin in plan["pins"]) / CREDITS_PER_USD
    console.print(f"This run ${spent / CREDITS_PER_USD:.2f}, all images ${total:.2f}. Preview: {preview}")


@cli.command()
@click.option("--account", default=None, help="Zernio account id when several Pinterest accounts are connected.")
def boards(account: str | None) -> None:
    """List the Pinterest boards of your Zernio account."""
    from .zernio import ZernioClient
    client = ZernioClient()
    found = client.account(account)
    console.print(f"@{found.get('username')} ({found['_id']})")
    for board in client.boards(found["_id"]):
        console.print(f"  {board['id']}  {board['name']}")


@cli.command()
@click.argument("folder")
@click.option("--account", default=None)
@click.option("--board", default=None, help="Put every pin on this board id instead of the planned boards.")
@click.option("--create-boards", is_flag=True, help="Create planned boards that do not exist yet.")
@click.option("--start", default=None, help="First slot, local time 'YYYY-MM-DD HH:MM' (default: tomorrow 20:00).")
@click.option("--every", default=24.0, show_default=True, help="Hours between pins.")
@click.option("--draft", is_flag=True, help="Save as Zernio drafts instead of scheduling.")
@click.option("--yes", is_flag=True, help="Schedule without asking. Published pins cannot be deleted.")
def publish(folder: str, account: str | None, board: str | None, create_boards: bool, start: str | None,
            every: float, draft: bool, yes: bool) -> None:
    """Schedule the rendered pins on Pinterest through Zernio."""
    from .zernio import ZernioClient
    plan, path = plans.load(folder)
    todo = publishing.queue(plan)
    if not todo:
        raise SystemExit("Nothing to publish: render the pins first.")
    client = ZernioClient()
    found = client.account(account)
    if board:
        board_ids = {pin["board"]: board for pin in todo}
    else:
        board_ids = publishing.match_boards(sorted({pin["board"] for pin in todo}), client.boards(found["_id"]))
    missing = [name for name, identity in board_ids.items() if not identity]
    if missing and not create_boards:
        raise SystemExit(f"Boards not found: {', '.join(missing)}. Pass --create-boards or --board <id> "
                         "(see: pin-engine boards).")
    first = datetime.strptime(start, "%Y-%m-%d %H:%M") if start else publishing.default_start()
    times = publishing.slots(len(todo), first, every)
    table = Table()
    for column in ("When", "Board", "Title"):
        table.add_column(column)
    for pin, when in zip(todo, times):
        table.add_row("draft" if draft else when.replace("T", " ")[:16],
                      pin["board"] + (" (new)" if pin["board"] in missing else ""), pin["title"])
    console.print(f"@{found.get('username')} · links to {plan['url']}")
    console.print(table)
    if not yes and not click.confirm("Schedule these pins? Published pins cannot be deleted through Zernio.", default=False):
        raise SystemExit(0)
    # Boards are created only after the yes: declining leaves the Pinterest account untouched.
    for name in missing:
        board_ids[name] = client.create_board(found["_id"], name)["id"]
    count = publishing.publish(plan, path.parent, client, found, board_ids, times, draft=draft, log=console.print)
    plans.save(plan, path)
    console.print(f"{count} of {len(todo)} pins {'saved as drafts' if draft else 'scheduled'}.")


@cli.command()
def stats() -> None:
    """Impressions, saves and clicks per published pin, best first. Saves matter most."""
    from .zernio import ZernioClient
    rows = publishing.stats(ZernioClient())
    table = Table()
    for column in ("Saves", "Clicks", "Impr.", "Angle", "Keyword", "Scheduled"):
        table.add_column(column)
    for row in rows:
        table.add_row(str(row["saves"]), str(row["clicks"]), str(row["impressions"]), row["angle"], row["keyword"],
                      (row.get("scheduled_for") or "")[:16])
    console.print(table if rows else "No published pins yet.")
    console.print("Pins mature over weeks on Pinterest; judge an angle after about 7 days.")


@cli.command()
def credits() -> None:
    """Raywake balance and what pin-engine has spent."""
    wallet = RaywakeClient().wallet()
    spent = total_spend()
    balance = wallet.get("available_credits", wallet.get("credits", 0))
    console.print(f"Raywake balance: ${float(balance) / CREDITS_PER_USD:.2f}  ·  images made: {spent['images']} "
                  f"(${spent['usd']:.2f})")
    console.print(f"Top up: {link('billing', 'credits')}")


def main() -> None:
    settings  # noqa: B018 - load .env early so missing keys fail with a clear message
    cli()


if __name__ == "__main__":
    main()
