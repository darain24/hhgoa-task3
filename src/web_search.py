"""Fetch one user-supplied public URL live; retain the original stage filename."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit

import requests

from config.settings import OUTPUT_DIR


class SearchAPIError(Exception):
    """The supplied URL could not be retrieved as a public HTML page."""


class _TitleParser(HTMLParser):
    """Extract the first HTML title without executing page code."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_title = False
        self.parts: list[str] = []
        self.finished = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title" and not self.finished:
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
            self.finished = True

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)


def _validate_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("https", "http") or not parsed.hostname:
            raise ValueError
        if parsed.username or parsed.password or any(ord(char) < 32 for char in url):
            raise ValueError
        return parsed.hostname.lower().removeprefix("www.")
    except ValueError:
        raise SearchAPIError(
            "Provide an absolute HTTP(S) post URL without credentials."
        ) from None


def fetch_known_post(post_url: str) -> dict[str, Any]:
    """Fetch a supplied URL live and save evidence; raise SearchAPIError on failure."""
    _validate_url(post_url)
    try:
        with requests.get(
            post_url,
            timeout=(10, 30),
            stream=True,
            headers={"User-Agent": "FaceRecordDemo/1.0", "Cache-Control": "no-cache"},
        ) as response:
            response.raise_for_status()
            domain = _validate_url(response.url)
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(
                kind in content_type for kind in ("text/html", "application/xhtml+xml")
            ):
                raise SearchAPIError("The URL must return a public HTML page.")
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) > 5 * 1024 * 1024:
                    raise SearchAPIError("Page exceeds the 5 MiB retrieval limit.")
            if not body:
                raise SearchAPIError("The server returned an empty page.")
            parser = _TitleParser()
            parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
            result = {
                "url": response.url,
                "title": " ".join("".join(parser.parts).split())[:500],
                "source_domain": domain,
                "thumbnail": "",
                "rank": 1,
                "page_content_sha256": hashlib.sha256(body).hexdigest(),
                "http_status": response.status_code,
            }
    except requests.RequestException:
        raise SearchAPIError(
            "Live URL retrieval failed; check URL, access and connection."
        ) from None
    evidence = {
        "provided_url": post_url,
        "query_timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        "selection_method": "user_provided_url",
        "results": [result],
        "selected_match": result,
    }
    try:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "search_results.json").write_text(
            json.dumps(evidence, indent=2) + "\n"
        )
    except OSError:
        raise SearchAPIError("Cannot save retrieval evidence to outputs/.") from None
    return evidence


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("post_url")
    try:
        evidence = fetch_known_post(parser.parse_args().post_url)
        print(json.dumps(evidence, indent=2))
    except SearchAPIError as error:
        print(f"Error [retrieval]: {error}", file=sys.stderr)
        sys.exit(1)
