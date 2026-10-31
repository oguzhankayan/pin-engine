"""Read the page a pin will link to: title, description, product photo, price and visible text."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import requests

UA = "Mozilla/5.0 (compatible; pin-engine/0.1; +https://github.com/oguzhankayan/pin-engine)"
SKIP = {"script", "style", "noscript", "svg", "template", "nav", "footer", "header"}


@dataclass
class Page:
    url: str
    title: str = ""
    description: str = ""
    images: list[str] = field(default_factory=list)
    price: str = ""
    site: str = ""
    text: str = ""

    def brief(self) -> dict:
        return {"url": self.url, "site": self.site, "title": self.title, "description": self.description,
                "price": self.price, "has_product_photo": bool(self.images), "text": self.text[:4000]}


class _Reader(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self.ld: list[str] = []
        self.text: list[str] = []
        self._stack: list[str] = []
        self._in_title = self._in_ld = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            if key and attrs.get("content") and key not in self.meta:
                self.meta[key] = attrs["content"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and (attrs.get("type") or "").lower() == "application/ld+json":
            self._in_ld = True
            self.ld.append("")
        if tag in SKIP:
            self._stack.append(tag)

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._in_ld = False
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._in_ld:
            self.ld[-1] += data
        elif not self._stack and data.strip():
            self.text.append(data.strip())


def _products(node):
    """Every schema.org Product in a JSON-LD tree."""
    if isinstance(node, list):
        for item in node:
            yield from _products(item)
    elif isinstance(node, dict):
        kind = node.get("@type")
        if kind == "Product" or (isinstance(kind, list) and "Product" in kind):
            yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _products(value)


def parse(url: str, html: str) -> Page:
    reader = _Reader()
    reader.feed(html)
    meta = reader.meta
    page = Page(url=url, site=meta.get("og:site_name") or urlsplit(url).netloc.removeprefix("www."))
    page.title = meta.get("og:title") or reader.title.strip()
    page.description = meta.get("og:description") or meta.get("description") or ""
    images = [meta[key] for key in ("og:image", "og:image:secure_url", "twitter:image") if meta.get(key)]
    for block in reader.ld:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for product in _products(data):
            page.title = page.title or product.get("name", "")
            page.description = page.description or product.get("description", "")
            photo = product.get("image")
            images += [photo] if isinstance(photo, str) else [p if isinstance(p, str) else p.get("url", "") for p in photo or []]
            offers = product.get("offers")
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if isinstance(offer, dict) and offer.get("price") and not page.price:
                page.price = f"{offer.get('price')} {offer.get('priceCurrency', '')}".strip()
    page.price = page.price or " ".join(filter(None, [meta.get("product:price:amount"), meta.get("product:price:currency")]))
    page.images = list(dict.fromkeys(urljoin(url, i) for i in images if i and i.startswith(("http", "/"))))
    page.text = re.sub(r"\s+", " ", " ".join(reader.text))
    return page


ETSY_LISTING = re.compile(r"(?:^|\.)etsy\.com$")


def read_etsy(url: str) -> Page:
    """An Etsy listing through Etsy's open API (public listing data, no shop login)."""
    from .config import settings
    match = re.search(r"/listing/(\d+)", urlsplit(url).path)
    if not match:
        raise SystemExit("Etsy links must point to a listing (etsy.com/listing/<id>/...).")
    if not (settings.etsy_api_key and settings.etsy_shared_secret):
        raise SystemExit("Etsy blocks direct page reads. Add ETSY_API_KEY and ETSY_SHARED_SECRET to .env, "
                         "or pass --title and --photo to plan.")
    response = requests.get(f"https://openapi.etsy.com/v3/application/listings/{match.group(1)}",
                            params={"includes": "Images,Shop"}, timeout=30,
                            headers={"x-api-key": f"{settings.etsy_api_key}:{settings.etsy_shared_secret}"})
    response.raise_for_status()
    data = response.json()
    price = data.get("price") or {}
    amount = f"{price['amount'] / price['divisor']:.2f} {price.get('currency_code', '')}" if price.get("divisor") else ""
    return Page(url=data.get("url") or url, title=data.get("title", ""), description=data.get("description", "")[:600],
                images=[image["url_fullxfull"] for image in data.get("images") or [] if image.get("url_fullxfull")],
                price=amount.strip(), site=(data.get("shop") or {}).get("shop_name") or "Etsy",
                text=data.get("description", ""))


def read(url: str) -> Page:
    if urlsplit(url).scheme != "https":
        raise SystemExit("Use an https link; Pinterest rejects other links.")
    if ETSY_LISTING.search(urlsplit(url).netloc):
        return read_etsy(url)
    response = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "en"}, timeout=30)
    response.raise_for_status()
    return parse(response.url, response.text)


def photo(page: Page) -> bytes | None:
    """The first product photo that downloads as an image."""
    for url in page.images[:3]:
        try:
            response = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            if response.ok and response.headers.get("content-type", "").startswith("image/"):
                return response.content
        except requests.RequestException:
            continue
    return None
