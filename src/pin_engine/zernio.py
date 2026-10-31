"""Zernio: the publishing channel. Pins go to Pinterest through your connected Zernio account.

A published pin cannot be edited (beyond its description) or deleted through Zernio,
so nothing here publishes without an explicit command.
"""
from __future__ import annotations

import mimetypes
import uuid
from pathlib import Path

import requests

from .config import settings


class ZernioError(RuntimeError):
    pass


class ZernioClient:
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or settings.zernio_api_key
        if not self.api_key:
            raise SystemExit("ZERNIO_API_KEY is not set. Create one at https://zernio.com and connect "
                             "your Pinterest account there.")
        self.base = settings.zernio_base_url.rstrip("/")

    def _request(self, method: str, path: str, *, params: dict | None = None, body: dict | None = None,
                 idempotent: bool = False) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}
        if idempotent:
            # A fresh id per logical call; reusing one makes later calls return the first post.
            headers["x-request-id"] = str(uuid.uuid4())
        response = requests.request(method, f"{self.base}{path}", params={k: v for k, v in (params or {}).items()
                                    if v is not None} or None, json=body, headers=headers, timeout=120)
        if response.status_code >= 300:
            raise ZernioError(f"{method} {path} -> {response.status_code}: {response.text[:400]}")
        return response.json() if response.content else {}

    def pinterest_accounts(self) -> list[dict]:
        return [a for a in self._request("GET", "/accounts").get("accounts", []) if a.get("platform") == "pinterest"]

    def account(self, account_id: str | None = None) -> dict:
        accounts = self.pinterest_accounts()
        if account_id:
            accounts = [a for a in accounts if a.get("_id") == account_id]
        if not accounts:
            raise SystemExit("No Pinterest account is connected in Zernio. Connect one in the Zernio dashboard.")
        if len(accounts) > 1 and not account_id:
            names = ", ".join(f"{a.get('username')} ({a['_id']})" for a in accounts)
            raise SystemExit(f"Several Pinterest accounts are connected; pass --account. Found: {names}")
        return accounts[0]

    def boards(self, account_id: str) -> list[dict]:
        return self._request("GET", f"/accounts/{account_id}/pinterest-boards").get("boards", [])

    def create_board(self, account_id: str, name: str, description: str = "") -> dict:
        response = self._request("POST", f"/accounts/{account_id}/pinterest-boards",
                                 body={"name": name, "description": description, "privacy": "PUBLIC"})
        return response.get("board", response)

    def upload(self, path: Path) -> str:
        """Host a local image on Zernio's storage; returns the URL for mediaItems.

        Zernio keeps unpublished uploads for 7 days, so upload close to the schedule."""
        content_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
        presigned = self._request("POST", "/media/presign", body={"filename": path.name, "contentType": content_type})
        put = requests.put(presigned["uploadUrl"], data=path.read_bytes(), headers={"Content-Type": content_type}, timeout=300)
        if put.status_code >= 300:
            raise ZernioError(f"media upload -> {put.status_code}: {put.text[:300]}")
        return presigned["publicUrl"]

    def create_pin(self, *, account_id: str, board_id: str, title: str, description: str, link: str,
                   media_url: str, media_type: str = "image", scheduled_for: str | None = None,
                   cover_url: str | None = None, draft: bool = False) -> dict:
        data = {"boardId": board_id, "title": title, "link": link, "isAiGenerated": True}
        if cover_url:
            data["coverImageUrl"] = cover_url
        body: dict = {"content": description, "mediaItems": [{"url": media_url, "type": media_type}],
                      "platforms": [{"platform": "pinterest", "accountId": account_id, "platformSpecificData": data}]}
        if draft:
            body["isDraft"] = True
        elif scheduled_for:
            body["scheduledFor"], body["timezone"] = scheduled_for, settings.pin_timezone
        else:
            body["publishNow"] = True
        response = self._request("POST", "/posts", body=body, idempotent=True)
        return response.get("post") or response.get("existingPost") or response

    def post_analytics(self, post_id: str) -> dict:
        return self._request("GET", "/analytics", params={"postId": post_id})
