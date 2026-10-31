<p align="center">
  <a href="https://raywake.si/?utm_source=github&utm_medium=pin-engine&utm_campaign=oss&utm_content=readme-logo">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="docs/assets/raywake-logo-dark.svg">
      <img src="docs/assets/raywake-logo-light.svg" alt="Raywake" width="200">
    </picture>
  </a>
</p>

<h1 align="center">pin-engine</h1>

<p align="center">
  <a href="https://raywake.si/?utm_source=github&utm_medium=pin-engine&utm_campaign=oss&utm_content=badge"><img alt="Images by Raywake" src="https://img.shields.io/badge/images%20by-Raywake-c3092d"></a>
  <a href="LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-222221"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-222221">
</p>

**Give Claude Code a product or blog link. It plans the Pinterest searches that page can win,
makes pins that show your real product, writes keyword-led titles and descriptions, checks
every image, and schedules the pins on your Pinterest account at a human pace.**

Pinterest works like a search engine: people search, save what answers them, and click
through. pin-engine is built around that: every pin targets a different search phrase, answers
it in the pin, and links back to your page.

```text
> /pin-engine https://your-shop.com/products/linen-apron
  read the page · wrote 5 pins (5 search phrases) · images $X, ok? · reviewed, redid pin 3
  · preview ready · schedule 5 pins, one a day from tomorrow 20:00? · scheduled
```

There is no separate AI key: Claude Code is the planner and the image reviewer. The CLI does
the parts that need no judgment.

> **Built by the team behind [Raywake](https://raywake.si/?utm_source=github&utm_medium=pin-engine&utm_campaign=oss&utm_content=disclosure)**,
> the image engine behind every pin. Publishing goes through [Zernio](https://zernio.com), so
> you don't need Pinterest API approval. Sister project: [etsy-engine](https://github.com/oguzhankayan/etsy-engine).

## What it does

```text
 read ──► plan ──────► render ──► review ─────► publish ──► stats
 CLI:     Claude Code:  Raywake:   Claude Code:   Zernio:     Zernio:
 page,    keywords,     product-   text, product  scheduled   saves, clicks,
 product  angles, copy, faithful   fidelity,      pins, one   impressions
 photo    scenes        2:3 pins   redo if bad    a day       per pin
```

- **Your images, your call.** By default the product photo from your page goes to the image
  model as a reference, so the pin places that exact product in a new scene. Prefer cheap
  text-to-image (`--model flux/schnell`, about $0.01 a pin), your own product photo
  (`--photo-only`), or your own files (put a file name in a pin's `image` field).
- **Search first.** Each pin gets its own search phrase, a title led by it and a description
  that answers it. No hashtags, no claims your page doesn't make.
- **Checked before you see it.** Claude Code looks at each image: a misspelled headline, stray
  text or a changed product gets fixed and made again.
- **Human cadence.** Pins are scheduled one per day in the evening by default, each on a board
  that matches its topic. Pins are marked as AI-generated on Pinterest.
- **Learns what works.** `pin-engine stats` ranks your pins by saves, the signal Pinterest uses
  to spread a pin.

## Quickstart

```bash
git clone https://github.com/oguzhankayan/pin-engine && cd pin-engine
python3 -m venv .venv && .venv/bin/pip install -e .
cp .env.example .env     # RAYWAKE_API_KEY, ZERNIO_API_KEY
.venv/bin/pin-engine credits
claude                   # then: /pin-engine https://your-shop.com/products/your-product
```

Keys: **Raywake** → [create an API key](https://raywake.si/api-keys?utm_source=github&utm_medium=pin-engine&utm_campaign=oss&utm_content=quickstart)
(scopes `generate` + `jobs:read`) · **Zernio** → [zernio.com](https://zernio.com), then connect your Pinterest account there.

## The CLI underneath

Claude Code runs these for you ([the skill](.claude/skills/pin-engine/SKILL.md)); you can too.

```bash
pin-engine read URL --count 5         # page facts, product.jpg and an empty plan.json
pin-engine check output/<folder>      # limits, empty fields, repeated keywords
pin-engine render output/<folder>     # images (asks before spending) and preview.html
pin-engine render output/<folder> --redo 3
pin-engine render output/<folder> --model flux/schnell   # text-to-image, about $0.01 a pin
pin-engine render output/<folder> --photo-only           # your product photo, no generation
pin-engine boards                     # your Pinterest boards through Zernio
pin-engine publish output/<folder> --create-boards    # shows the schedule, asks, then schedules
pin-engine stats                      # saves, clicks, impressions per pin
```

`plan.json` is yours to edit: change a title, a scene or a board name and render again. `publish --every 48` spaces pins two days apart; `--start "2026-11-03 19:00"` sets
the first slot; `--draft` saves them in Zernio without scheduling.

Etsy listings are read through Etsy's open API (`ETSY_API_KEY` + `ETSY_SHARED_SECRET`). For any
page that can't be read, pass `--title "..." --photo product.jpg`.

## What a pin costs

Each image is quoted by Raywake before it runs and `render` asks before spending. The total is
printed at the end and in `preview.html`; `pin-engine credits` shows your balance.

Claude Code does the planning and image review in your own session; there is no other AI bill.

[Top up Raywake credits →](https://raywake.si/billing?utm_source=github&utm_medium=pin-engine&utm_campaign=oss&utm_content=readme-cost)

## Good to know

- Published pins cannot be edited or deleted through Zernio; `publish` always shows the
  schedule and asks first.
- Pinterest judges pins over weeks. Read `stats` after about 7 days before changing angles.
- Zernio keeps an unpublished upload for 7 days, so schedule within a week of publishing.

MIT licensed. Fork it, change anything.
