"""Raywake image client: every pin image is made here.

  1. POST /v1/quotes   {"model", "input"}                       -> {"quote_id", "credits"}
  2. POST /v1/generate {"model", "quote_id", "input"} + Idempotency-Key (?wait=true)
  3. GET  /v1/jobs/{job_id}                                      -> {"status", "outputs"}

A timeout is not proof of failure: retries reuse the same Idempotency-Key, so they
return the existing job instead of paying for a new one. Held states are never
treated as success and never resubmitted.
"""
from __future__ import annotations

import base64
import io
import json
import time
import uuid

import requests

from .config import DATA_DIR, PIN_SIZE, settings

SPEND_LOG = DATA_DIR / "raywake_spend.jsonl"
CREDITS_PER_USD = 100
BODY_BUDGET = 900_000  # inline reference bytes per request; Raywake caps a body near 1 MB
REF_MAX_SIDE = 1280


def link(path: str = "", content: str = "cli") -> str:
    return (f"https://raywake.si/{path.lstrip('/')}?utm_source=github"
            f"&utm_medium=pin-engine&utm_campaign=oss&utm_content={content}")


ERRORS = {
    400: "Bad request (input not accepted by this model)", 401: "Unauthorized (bad or revoked API key)",
    402: f"Out of Raywake credits. Top up: {link('billing', 'out-of-credits')}",
    403: "Forbidden (the key needs the generate and jobs:read scopes)",
    409: "Conflict (quote expired or input changed)", 413: "Request too large", 429: "Rate limited",
}
TRANSIENT = {429, 500, 502, 503, 504}
DONE = {"succeeded", "completed"}
FAILED = {"failed", "canceled", "cancelled", "rejected", "expired"}
HELD = {"needs_review", "needs_reconciliation", "submission_unknown"}


class RaywakeError(RuntimeError):
    pass


class RaywakeJobUnknown(RaywakeError):
    """The job may exist and may be charged; never retried automatically."""


def image_size(size: str) -> dict:
    width, height = (int(part) for part in size.lower().split("x"))
    return {"width": width, "height": height}


def reference(image: bytes, max_bytes: int = BODY_BUDGET) -> str:
    """A product photo as a JPEG data URI small enough to send inline."""
    from PIL import Image
    picture = Image.open(io.BytesIO(image))
    if picture.mode not in ("RGB", "L"):
        picture = picture.convert("RGB")
    side, quality = REF_MAX_SIDE, 85
    while True:
        scaled = picture.copy()
        scaled.thumbnail((side, side))
        buffer = io.BytesIO()
        scaled.save(buffer, format="JPEG", quality=quality, optimize=True)
        uri = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
        if len(uri) <= max_bytes or side <= 384:
            return uri
        if quality > 60:
            quality -= 10
        else:
            side = int(side * 0.8)


class RaywakeClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.raywake_api_key
        self.base = settings.raywake_base_url.rstrip("/")
        # A chosen model (e.g. flux/schnell) makes every pin from text; the default edits the product photo.
        self.model = model

    def _headers(self, idempotency_key: str | None = None) -> dict:
        if not self.api_key:
            raise SystemExit("RAYWAKE_API_KEY is not set. Create a key with the generate and jobs:read "
                             f"scopes: {link('api-keys', 'missing-key')}")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json",
                   "User-Agent": "pin-engine (+https://raywake.si)"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request(self, method: str, path: str, *, body: dict | None = None, params: dict | None = None,
                 idempotency_key: str | None = None, timeout: int = 60, retries: int = 4) -> dict:
        last = ""
        for attempt in range(retries):
            try:
                response = requests.request(method, f"{self.base}{path}", json=body, params=params,
                                            headers=self._headers(idempotency_key), timeout=timeout)
            except requests.RequestException as error:
                last = str(error)[:160]
                time.sleep(2 * (attempt + 1))
                continue
            if response.status_code < 300:
                return response.json()
            if response.status_code in TRANSIENT:
                last = f"{response.status_code} {ERRORS.get(response.status_code, '')}"
                wait = response.headers.get("Retry-After")
                time.sleep(float(wait) if wait and wait.isdigit() else 3 * (attempt + 1))
                continue
            raise RaywakeError(f"{method} {path} -> {response.status_code} "
                               f"{ERRORS.get(response.status_code, 'Error')}: {response.text[:300]}")
        raise RaywakeError(f"{method} {path} failed after {retries} attempts: {last}")

    def build_input(self, prompt: str, references: list[str] | None = None, size: str = PIN_SIZE) -> tuple[str, dict]:
        if self.model:
            model, references = self.model, None
        else:
            model = settings.raywake_edit_model if references else settings.raywake_model
        data = {"prompt": prompt, "image_size": image_size(size), "num_images": 1}
        if model.startswith("openai/gpt-image"):
            data.update(quality=settings.raywake_quality, output_format="jpeg")
        if references:
            data["image_urls"] = references[:4]
        return model, data

    def quote(self, prompt: str, references: list[str] | None = None) -> dict:
        """A free price check: {"quote_id", "credits", ...}."""
        model, data = self.build_input(prompt, references)
        return {**self._request("POST", "/v1/quotes", body={"model": model, "input": data}), "model": model}

    def generate(self, prompt: str, references: list[str] | None = None, timeout: int = 300) -> tuple[bytes, float]:
        """One pin image: (jpeg bytes, credits charged)."""
        model, data = self.build_input(prompt, references)
        quote = self._request("POST", "/v1/quotes", body={"model": model, "input": data})
        key = str(uuid.uuid4())
        try:
            job = self._request("POST", "/v1/generate", params={"wait": "true"}, idempotency_key=key,
                                body={"model": model, "quote_id": quote["quote_id"], "input": data}, timeout=timeout)
        except RaywakeError as error:
            if "failed after" in str(error):
                raise RaywakeJobUnknown(f"generate outcome unknown (Idempotency-Key {key}): {error}") from error
            raise
        job = self._await(job, timeout)
        url = job.get("image_url") or next((o.get("url") for o in job.get("outputs") or [] if o.get("url")), None)
        if not url:
            raise RaywakeJobUnknown(f"job {job.get('job_id')} succeeded without an output")
        image = self._download(url)
        # charged_credits is what the run cost; credits is the hold taken before it.
        credits = float(job.get("charged_credits") or job.get("credits") or quote.get("credits") or 0)
        record_spend(job.get("job_id"), model, credits)
        return image, credits

    def _await(self, job: dict, timeout: int) -> dict:
        deadline = time.time() + timeout
        while True:
            status = (job.get("status") or "").lower()
            if status in DONE:
                return job
            if status in FAILED:
                raise RaywakeError(f"job {job.get('job_id')} {status}: {job.get('error') or ''}")
            if status in HELD:
                raise RaywakeJobUnknown(f"job {job.get('job_id')} held ({status}); check it at https://raywake.si")
            if time.time() > deadline:
                raise RaywakeJobUnknown(f"timed out waiting for job {job.get('job_id')} ({status})")
            time.sleep(4)
            try:
                job = self._request("GET", f"/v1/jobs/{job['job_id']}")
            except RaywakeError as error:
                raise RaywakeJobUnknown(f"lost track of job {job.get('job_id')}: {error}") from error

    def _download(self, url: str) -> bytes:
        last = ""
        for attempt in range(4):
            try:
                response = requests.get(url, timeout=120)
                response.raise_for_status()
                return response.content
            except requests.RequestException as error:
                last = str(error)[:160]
                time.sleep(2 * (attempt + 1))
        raise RaywakeJobUnknown(f"output download failed: {last}")

    def wallet(self) -> dict:
        return self._request("GET", "/v1/wallet")


def record_spend(job_id, model: str, credits: float) -> None:
    SPEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    with SPEND_LOG.open("a") as handle:
        handle.write(json.dumps({"time": int(time.time()), "job_id": job_id, "model": model, "credits": credits}) + "\n")


def total_spend() -> dict:
    credits, images = 0.0, 0
    if SPEND_LOG.exists():
        for line in SPEND_LOG.read_text().splitlines():
            try:
                credits += float(json.loads(line).get("credits") or 0)
                images += 1
            except (ValueError, TypeError):
                continue
    return {"credits": round(credits, 2), "usd": round(credits / CREDITS_PER_USD, 2), "images": images}
