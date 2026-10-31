"""pin-engine CLI: plan → render → publish → stats."""
from __future__ import annotations

import webbrowser
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


def _plan(url: str, count: int, language: str, title: str | None, photo: str | None) -> tuple[dict, Path]:
    try:
        page = pages.read(url)
    except (SystemExit, Exception) as error:  # noqa: BLE001
        if not title:
            raise SystemExit(f"Could not read {url}: {error}. Pass --title (and --photo) to plan without reading it.")
        page = pages.Page(url=url, title=title, site=urlsplit(url).netloc.removeprefix("www."))
    if title:
        page.title = title
    image = Path(photo).expanduser().read_bytes() if photo else pages.photo(page)
    page.images = page.images or ([photo] if photo else [])
    result = plans.make(page, count=count, language=language)
    result["product_photo"] = bool(image)
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
    """Turn a product or post link into Pinterest pins. Images by Raywake, publishing by Zernio."""


@cli.command()
@click.argument("url")
@click.option("--count", default=5, show_default=True, help="Pins to plan.")
@click.option("--language", default="English", show_default=True)
@click.option("--title", default=None, help="Product or post title, when the page cannot be read.")
@click.option("--photo", default=None, type=click.Path(exists=True), help="Local product photo to keep in every pin.")
def plan(url: str, count: int, language: str, title: str | None, photo: str | None) -> None:
    """Read URL and write a pin plan (no images, no cost beyond a Claude call)."""
    result, path = _plan(url, count, language, title, photo)
    _show(result)
    console.print(f"Plan saved: {path}\nEdit it if you like, then: pin-engine render {path.parent}")


@cli.command()
@click.argument("folder")
@click.option("--yes", is_flag=True, help="Skip the cost confirmation.")
@click.option("--rerolls", default=1, show_default=True, help="New attempts when the image check fails.")
@click.option("--no-check", is_flag=True, help="Skip the Claude image check.")
def render(folder: str, yes: bool, rerolls: int, no_check: bool) -> None:
    """Make the pin images with Raywake and open a local preview."""
    plan, path = plans.load(folder)
    for pin in plan["pins"]:
        pin["problems"] = plans.problems(pin)
    product, references = _product(path.parent)
    client = RaywakeClient()
    credits = rendering.estimate(plan, references, client)
    if credits and not yes:
        click.confirm(f"Images will cost about ${credits / CREDITS_PER_USD:.2f} "
                      f"(plus a retry when a check fails). Continue?", abort=True)
    rendering.render(plan, path.parent, product, references, client, rerolls=rerolls, qc=not no_check, log=console.print)
    plans.save(plan, path)
    preview = rendering.preview(plan, path.parent)
    spent = sum(pin.get("credits") or 0 for pin in plan["pins"]) / CREDITS_PER_USD
    console.print(f"Images: ${spent:.2f}. Preview: {preview}")
    webbrowser.open(preview.as_uri())


@cli.command()
@click.argument("url")
@click.option("--count", default=3, show_default=True)
@click.option("--language", default="English", show_default=True)
@click.option("--title", default=None)
@click.option("--photo", default=None, type=click.Path(exists=True))
@click.option("--yes", is_flag=True)
@click.pass_context
def demo(ctx: click.Context, url: str, count: int, language: str, title: str | None, photo: str | None, yes: bool) -> None:
    """plan + render for one link, nothing published."""
    result, path = _plan(url, count, language, title, photo)
    _show(result)
    ctx.invoke(render, folder=str(path.parent), yes=yes, rerolls=1, no_check=False)


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
        for name in missing:
            board_ids[name] = client.create_board(found["_id"], name)["id"]
    first = datetime.strptime(start, "%Y-%m-%d %H:%M") if start else publishing.default_start()
    times = publishing.slots(len(todo), first, every)
    table = Table()
    for column in ("When", "Board", "Title"):
        table.add_column(column)
    for pin, when in zip(todo, times):
        table.add_row("draft" if draft else when.replace("T", " ")[:16], pin["board"], pin["title"])
    console.print(f"@{found.get('username')} · links to {plan['url']}")
    console.print(table)
    if not yes and not click.confirm("Schedule these pins? Published pins cannot be deleted through Zernio.", default=False):
        raise SystemExit(0)
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
    from .llm import total_spend as claude_spend
    balance = wallet.get("available_credits", wallet.get("credits", 0))
    console.print(f"Raywake balance: ${float(balance) / CREDITS_PER_USD:.2f}  ·  images made: {spent['images']} "
                  f"(${spent['usd']:.2f})  ·  Claude: ${claude_spend():.2f}")
    console.print(f"Top up: {link('billing', 'credits')}")


def main() -> None:
    settings  # noqa: B018 - load .env early so missing keys fail with a clear message
    cli()


if __name__ == "__main__":
    main()
