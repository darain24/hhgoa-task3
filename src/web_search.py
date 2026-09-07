"""Fetch one user-supplied public URL live; retain the original stage filename."""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image
import requests

from config.settings import OUTPUT_DIR, get_serpapi_key


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


def fetch_known_post(
    post_url: str,
    selection_method: str = "user_provided_url",
    rank: int = 1,
) -> dict[str, Any]:
    """Fetch a supplied URL live and save evidence; raise SearchAPIError on failure."""
    _validate_url(post_url)
    try:
        with requests.get(
            post_url,
            timeout=(10, 30),
            stream=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Cache-Control": "no-cache",
            },
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
                "rank": rank,
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
        "selection_method": selection_method,
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


def _prepare_image_for_serpapi(image_path: str) -> tuple[str, bytes, str]:
    """Ensure image is under SerpApi's 500 KB limit by resizing/compressing if needed."""
    raw = Path(image_path).read_bytes()
    if len(raw) <= 450 * 1024:
        return Path(image_path).name, raw, "image/jpeg"
    with Image.open(BytesIO(raw)) as img:
        img = img.convert("RGB")
        img.thumbnail((1024, 1024))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85, optimize=True)
        compressed = buf.getvalue()
        if len(compressed) > 450 * 1024:
            buf = BytesIO()
            img.thumbnail((800, 800))
            img.save(buf, format="JPEG", quality=75, optimize=True)
            compressed = buf.getvalue()
        return "search_image.jpg", compressed, "image/jpeg"


SOCIAL_PRIORITY = (
    "x.com",
    "twitter.com",
    "reddit.com",
    "facebook.com",
    "linkedin.com",
    "youtube.com",
    "instagram.com",
    "threads.net",
    "tiktok.com",
    "pinterest.com",
)


def _get_social_platform(url: str) -> str | None:
    try:
        domain = _validate_url(url)
        return next(
            (p for p in SOCIAL_PRIORITY if domain == p or domain.endswith("." + p)),
            None,
        )
    except SearchAPIError:
        return None


def _extract_entity_info(search_data: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Extract recognized subject/entity from Google Lens response to verify matches."""
    # 1. Related content query
    for rc in search_data.get("related_content", []):
        query = rc.get("query", "").strip()
        if query:
            keywords = [
                w.lower()
                for w in query.replace("-", " ").replace("|", " ").split()
                if len(w) > 2
            ]
            return query, keywords

    # 2. Knowledge graph title
    kg = search_data.get("knowledge_graph", {})
    if kg.get("title"):
        title = kg["title"].strip()
        keywords = [
            w.lower()
            for w in title.replace("-", " ").replace("|", " ").split()
            if len(w) > 2
        ]
        return title, keywords

    # 3. Organic results top title
    org_results = search_data.get("organic_results", [])
    if org_results:
        top_title = org_results[0].get("title", "").strip()
        clean_title = top_title.split("-")[0].split("|")[0].split("–")[0].strip()
        if clean_title:
            keywords = [w.lower() for w in clean_title.split() if len(w) > 2]
            return clean_title, keywords

    return None, []


def search_image_with_serpapi(image_path: str) -> dict[str, Any]:
    """Find a verified public/social URL via SerpApi; raise SearchAPIError if face is not public."""
    api_key = get_serpapi_key()
    try:
        filename, data_bytes, content_type = _prepare_image_for_serpapi(image_path)
        upload_resp = requests.post(
            "https://serpapi.com/image",
            files={"image": (filename, data_bytes, content_type)},
            data={"api_key": api_key},
            timeout=30,
        )
        if upload_resp.status_code != 200:
            err_msg = ""
            try:
                err_msg = upload_resp.json().get("error", "")
            except Exception:
                pass
            raise SearchAPIError(
                f"SerpApi upload failed ({upload_resp.status_code}): {err_msg or upload_resp.text[:200]}"
            )

        upload_data = upload_resp.json()
        image_id = upload_data.get("image_id")
        if not image_id:
            raise SearchAPIError("SerpApi did not return an image_id.")

        search_resp = requests.get(
            "https://serpapi.com/search",
            params={
                "engine": "google_lens",
                "image_id": image_id,
                "api_key": api_key,
            },
            timeout=30,
        )
        if search_resp.status_code != 200:
            err_msg = ""
            try:
                err_msg = search_resp.json().get("error", "")
            except Exception:
                pass
            raise SearchAPIError(
                f"SerpApi search failed ({search_resp.status_code}): {err_msg or search_resp.text[:200]}"
            )

        search_data = search_resp.json()
    except SearchAPIError:
        raise
    except requests.RequestException as exc:
        raise SearchAPIError(f"SerpApi network request failed: {exc}") from None
    except ValueError:
        raise SearchAPIError("SerpApi returned invalid JSON.") from None

    # Verify that Google Lens recognized an actual public presence for the face
    entity_name, entity_keywords = _extract_entity_info(search_data)
    if not entity_name or not entity_keywords:
        raise SearchAPIError(
            "No verified public web or social media match found for this face."
        )

    # Combine candidates from organic_results and visual_matches
    seen_urls: set[str] = set()
    all_candidates: list[dict[str, Any]] = []

    for pos, item in enumerate(search_data.get("organic_results", [])):
        link = item.get("link")
        if link and link.startswith("http") and link not in seen_urls:
            seen_urls.add(link)
            all_candidates.append(
                {"link": link, "title": item.get("title", ""), "rank": pos + 1}
            )

    for pos, item in enumerate(search_data.get("visual_matches", [])):
        link = item.get("link")
        if link and link.startswith("http") and link not in seen_urls:
            seen_urls.add(link)
            all_candidates.append(
                {"link": link, "title": item.get("title", ""), "rank": pos + 1}
            )

    # Filter candidates to only those whose title or URL contains the entity keywords
    verified_social: list[tuple[int, int, dict[str, Any]]] = []
    verified_web: list[dict[str, Any]] = []

    for cand in all_candidates:
        link = cand["link"]
        title_lower = cand["title"].lower()
        link_lower = link.lower()
        is_relevant = any(
            kw in title_lower or kw in link_lower for kw in entity_keywords
        )
        if not is_relevant:
            continue

        plat = _get_social_platform(link)
        if plat:
            verified_social.append((SOCIAL_PRIORITY.index(plat), cand["rank"], cand))
        else:
            verified_web.append(cand)

    # Sort social posts by platform priority (X/Twitter, Reddit, Facebook, LinkedIn, YouTube, Instagram...)
    verified_social.sort(key=lambda x: (x[0], x[1]))

    # 1. Attempt retrieval of verified social media posts
    for _, _, cand in verified_social:
        try:
            return fetch_known_post(
                cand["link"],
                selection_method="serpapi_social_match",
                rank=cand["rank"],
            )
        except SearchAPIError:
            continue

    # 2. Fallback to verified public web pages
    for cand in verified_web:
        try:
            return fetch_known_post(
                cand["link"],
                selection_method="serpapi_google_lens",
                rank=cand["rank"],
            )
        except SearchAPIError:
            continue

    raise SearchAPIError(
        "No verified public page for this face could be retrieved."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("post_url")
    try:
        evidence = fetch_known_post(parser.parse_args().post_url)
        print(json.dumps(evidence, indent=2))
    except SearchAPIError as error:
        print(f"Error [retrieval]: {error}", file=sys.stderr)
        sys.exit(1)
