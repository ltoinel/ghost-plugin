#!/usr/bin/env python3
"""Ghost Admin API CLI.

A small, dependency-light wrapper around the Ghost CMS Admin API for the
operations most commonly needed when drafting/publishing blog posts:

    list-posts   — fetch recent posts (metadata)
    get-post     — fetch a single post by id or slug
    create-post  — create a post from a Markdown file
    update-post  — update fields on an existing post (handles updated_at)
    delete-post  — delete a post by id or slug

Authentication:
    Set GHOST_ADMIN_API_URL (e.g. https://example.ghost.io) and
    GHOST_ADMIN_API_KEY (format: {id}:{secret}). The key comes from
    Ghost Admin → Settings → Integrations → Custom integration.

The script generates a short-lived JWT per request (HS256 over the secret,
aud=/admin/, 5-minute expiry), so each call is self-contained.

Dependencies: Python 3.8+ stdlib. The `markdown` package is lazily
installed on first use of create-post/update-post --markdown.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Auth: generate a JWT from the Admin API key
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def make_jwt(api_key: str) -> str:
    """Generate a short-lived JWT for the Ghost Admin API.

    The key format is `{id}:{secret}` where both are hex strings. The id
    goes in the JWT header as `kid`; the secret is hex-decoded and used
    as the HMAC-SHA256 key. `aud` must be `/admin/`; Ghost rejects
    otherwise.
    """
    if ":" not in api_key:
        raise ValueError(
            "GHOST_ADMIN_API_KEY must be in the form '{id}:{secret}' — "
            "get it from Ghost Admin → Settings → Integrations."
        )
    key_id, secret_hex = api_key.split(":", 1)
    try:
        secret = bytes.fromhex(secret_hex)
    except ValueError as e:
        raise ValueError(
            "GHOST_ADMIN_API_KEY secret is not valid hex — double-check "
            "the key was copied cleanly."
        ) from e

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT", "kid": key_id}
    payload = {"iat": now, "exp": now + 5 * 60, "aud": "/admin/"}

    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    )
    sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url(sig)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class GhostError(Exception):
    """Raised when the Ghost API returns a non-2xx response."""

    def __init__(self, status: int, body: str, url: str):
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"Ghost API {status} on {url}: {body[:300]}")


def _config() -> Tuple[str, str]:
    url = os.environ.get("GHOST_ADMIN_API_URL", "").rstrip("/")
    key = os.environ.get("GHOST_ADMIN_API_KEY", "")
    missing = [name for name, val in (("GHOST_ADMIN_API_URL", url), ("GHOST_ADMIN_API_KEY", key)) if not val]
    if missing:
        raise SystemExit(
            "error: missing environment variables: " + ", ".join(missing) +
            "\n  GHOST_ADMIN_API_URL should be your blog base URL (e.g. https://example.ghost.io)."
            "\n  GHOST_ADMIN_API_KEY comes from Ghost Admin → Settings → Integrations."
        )
    # Strip any /ghost/api/... suffix a user might have pasted by mistake.
    url = re.sub(r"/ghost/api.*$", "", url)
    return url, key


def _request(
    method: str,
    path: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base_url, api_key = _config()
    token = make_jwt(api_key)

    qs = ""
    if params:
        qs = "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    url = f"{base_url}/ghost/api/admin{path}{qs}"

    data = None
    headers = {
        "Authorization": f"Ghost {token}",
        "Accept-Version": "v5.0",
        "User-Agent": "ghost-skill/1.0",
    }
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        raise GhostError(e.code, raw, url) from None


# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Return (metadata_dict, body_without_frontmatter).

    Supports a minimal YAML-ish subset: `key: value` and `key: [a, b, c]`.
    Good enough for the fields we care about.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    meta: Dict[str, Any] = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            items = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
            meta[key] = items
        else:
            meta[key] = value.strip("'\"")
    return meta, text[m.end():]


def _extract_h1(body: str) -> Tuple[Optional[str], str]:
    """If body starts with an H1, return (title, body_without_h1)."""
    m = re.match(r"^\s*#\s+(.+?)\s*\n", body)
    if not m:
        return None, body
    return m.group(1).strip(), body[m.end():]


def _markdown_to_html(md_text: str) -> str:
    try:
        import markdown  # type: ignore
    except ImportError:
        import subprocess
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--quiet", "markdown"],
            stdout=subprocess.DEVNULL,
        )
        import markdown  # type: ignore
    return markdown.markdown(
        md_text,
        extensions=["extra", "tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )


def _load_markdown_post(
    path: str,
    *,
    override_title: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse a markdown file into a partial Ghost post dict.

    Returned keys may include: title, html, tags, status, excerpt, slug,
    feature_image, published_at (from publish_at frontmatter).
    """
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    meta, body = _parse_frontmatter(text)

    title = override_title or meta.get("title")
    if not title:
        inferred_title, body = _extract_h1(body)
        title = inferred_title or os.path.splitext(os.path.basename(path))[0]
    else:
        # Still strip H1 if it duplicates the title.
        stripped_title, stripped_body = _extract_h1(body)
        if stripped_title and stripped_title.lower().strip() == title.lower().strip():
            body = stripped_body

    html = _markdown_to_html(body)
    post: Dict[str, Any] = {"title": title, "html": html}

    tags = meta.get("tags")
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    if tags:
        post["tags"] = [{"name": t} for t in tags]

    for key in ("status", "excerpt", "slug", "feature_image"):
        if meta.get(key):
            post[key] = meta[key]

    if meta.get("publish_at"):
        post["published_at"] = meta["publish_at"]

    return post


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_HEX24 = re.compile(r"^[a-f0-9]{24}$", re.IGNORECASE)


def _is_object_id(s: str) -> bool:
    return bool(_HEX24.match(s))


def _resolve_post_path(id_or_slug: str) -> str:
    """Return the API path segment for GET/PUT/DELETE on a single post."""
    if _is_object_id(id_or_slug):
        return f"/posts/{id_or_slug}/"
    return f"/posts/slug/{urllib.parse.quote(id_or_slug)}/"


def _parse_csv(s: Optional[str]) -> Optional[List[str]]:
    if s is None:
        return None
    return [x.strip() for x in s.split(",") if x.strip()]


def _print_json(obj: Any) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list_posts(args: argparse.Namespace) -> None:
    params: Dict[str, Any] = {
        "limit": args.limit,
        "order": "published_at desc,created_at desc",
    }
    if args.status and args.status != "all":
        params["filter"] = f"status:{args.status}"
    if args.fields:
        params["fields"] = args.fields
    else:
        params["fields"] = "id,title,slug,status,published_at,updated_at,url,visibility"

    data = _request("GET", "/posts/", params=params)
    posts = data.get("posts", [])
    _print_json({"count": len(posts), "posts": posts})


def cmd_get_post(args: argparse.Namespace) -> None:
    path = _resolve_post_path(args.id_or_slug)
    params: Dict[str, Any] = {}
    if args.include_html:
        params["formats"] = "html"
    data = _request("GET", path, params=params)
    posts = data.get("posts", [])
    if not posts:
        raise SystemExit(f"error: post not found: {args.id_or_slug}")
    post = posts[0]
    if not args.include_html:
        post.pop("html", None)
        post.pop("lexical", None)
        post.pop("mobiledoc", None)
    _print_json(post)


def _build_post_from_flags(args: argparse.Namespace) -> Dict[str, Any]:
    """Build a post dict from CLI flags, optionally starting from a markdown file."""
    post: Dict[str, Any] = {}
    if getattr(args, "markdown", None):
        post = _load_markdown_post(
            args.markdown,
            override_title=getattr(args, "title", None),
        )
    elif getattr(args, "title", None):
        post["title"] = args.title

    # CLI flags override frontmatter / inferred values.
    if getattr(args, "title", None):
        post["title"] = args.title
    if getattr(args, "status", None):
        post["status"] = args.status
    if getattr(args, "tags", None):
        tags = _parse_csv(args.tags) or []
        post["tags"] = [{"name": t} for t in tags]
    if getattr(args, "feature_image", None):
        post["feature_image"] = args.feature_image
    if getattr(args, "excerpt", None):
        post["excerpt"] = args.excerpt
    if getattr(args, "slug", None):
        post["slug"] = args.slug
    if getattr(args, "publish_at", None):
        post["published_at"] = args.publish_at

    return post


def cmd_create_post(args: argparse.Namespace) -> None:
    post = _build_post_from_flags(args)
    if "title" not in post:
        raise SystemExit("error: a title is required (pass --title or include an H1 in the markdown)")
    # Default to draft — safest.
    post.setdefault("status", "draft")

    body = {"posts": [post]}
    data = _request("POST", "/posts/", params={"source": "html"}, body=body)
    created = data.get("posts", [{}])[0]
    _print_json({
        "created": True,
        "id": created.get("id"),
        "slug": created.get("slug"),
        "status": created.get("status"),
        "url": created.get("url"),
        "title": created.get("title"),
    })


def cmd_update_post(args: argparse.Namespace) -> None:
    # Fetch current state first — we need updated_at for concurrency,
    # and we may need to merge tags for --add-tags.
    path = _resolve_post_path(args.id_or_slug)
    current_data = _request("GET", path)
    current = current_data.get("posts", [{}])[0]
    if not current.get("id"):
        raise SystemExit(f"error: post not found: {args.id_or_slug}")

    updates = _build_post_from_flags(args)

    # Handle tag semantics: --set-tags replaces, --add-tags appends.
    if getattr(args, "set_tags", None):
        tags = _parse_csv(args.set_tags) or []
        updates["tags"] = [{"name": t} for t in tags]
    elif getattr(args, "add_tags", None):
        existing = [t.get("name") for t in current.get("tags") or [] if t.get("name")]
        new = _parse_csv(args.add_tags) or []
        merged = existing + [t for t in new if t not in existing]
        updates["tags"] = [{"name": t} for t in merged]

    if not updates:
        raise SystemExit("error: no updates provided (pass at least one of --markdown, --title, --status, etc.)")

    updates["updated_at"] = current["updated_at"]

    # Use the resolved id for the PUT (slug-based paths work for GET but id is canonical).
    put_path = f"/posts/{current['id']}/"
    body = {"posts": [updates]}
    params = {"source": "html"} if "html" in updates else None

    try:
        data = _request("PUT", put_path, params=params, body=body)
    except GhostError as e:
        # If someone else changed it between our GET and our PUT, retry once.
        if e.status == 409 or "updated_at" in e.body.lower():
            refresh = _request("GET", put_path).get("posts", [{}])[0]
            updates["updated_at"] = refresh["updated_at"]
            body = {"posts": [updates]}
            data = _request("PUT", put_path, params=params, body=body)
        else:
            raise

    updated = data.get("posts", [{}])[0]
    _print_json({
        "updated": True,
        "id": updated.get("id"),
        "slug": updated.get("slug"),
        "status": updated.get("status"),
        "url": updated.get("url"),
        "title": updated.get("title"),
    })


def cmd_delete_post(args: argparse.Namespace) -> None:
    # DELETE needs the id, not the slug. Resolve if needed.
    if _is_object_id(args.id_or_slug):
        post_id = args.id_or_slug
    else:
        data = _request("GET", _resolve_post_path(args.id_or_slug))
        posts = data.get("posts", [])
        if not posts:
            raise SystemExit(f"error: post not found: {args.id_or_slug}")
        post_id = posts[0]["id"]

    _request("DELETE", f"/posts/{post_id}/")
    _print_json({"deleted": True, "id": post_id})


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ghost.py",
        description="Ghost CMS Admin API client. Reads GHOST_ADMIN_API_URL and GHOST_ADMIN_API_KEY from env.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lp = sub.add_parser("list-posts", help="List recent posts")
    lp.add_argument("--limit", type=int, default=15)
    lp.add_argument("--status", choices=["draft", "published", "scheduled", "all"], default="all")
    lp.add_argument("--fields", help="Comma-separated list of fields to return")
    lp.set_defaults(func=cmd_list_posts)

    gp = sub.add_parser("get-post", help="Get a single post by id or slug")
    gp.add_argument("id_or_slug")
    gp.add_argument("--include-html", action="store_true", help="Include rendered HTML body (bigger response)")
    gp.set_defaults(func=cmd_get_post)

    cp = sub.add_parser("create-post", help="Create a post from a markdown file")
    cp.add_argument("markdown", help="Path to a .md file")
    cp.add_argument("--title")
    cp.add_argument("--status", choices=["draft", "published", "scheduled"])
    cp.add_argument("--tags", help="Comma-separated tag names")
    cp.add_argument("--feature-image", dest="feature_image")
    cp.add_argument("--excerpt")
    cp.add_argument("--slug")
    cp.add_argument("--publish-at", dest="publish_at", help="ISO-8601 timestamp for scheduled posts")
    cp.set_defaults(func=cmd_create_post)

    up = sub.add_parser("update-post", help="Update fields on an existing post")
    up.add_argument("id_or_slug")
    up.add_argument("--markdown", help="Replace body with contents of this markdown file")
    up.add_argument("--title")
    up.add_argument("--status", choices=["draft", "published", "scheduled"])
    up.add_argument("--add-tags", dest="add_tags", help="Tags to add (comma-separated)")
    up.add_argument("--set-tags", dest="set_tags", help="Tags to set, replacing existing (comma-separated)")
    up.add_argument("--feature-image", dest="feature_image")
    up.add_argument("--excerpt")
    up.add_argument("--publish-at", dest="publish_at")
    up.set_defaults(func=cmd_update_post)

    dp = sub.add_parser("delete-post", help="Delete a post")
    dp.add_argument("id_or_slug")
    dp.set_defaults(func=cmd_delete_post)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except GhostError as e:
        print(f"error: Ghost API returned {e.status}", file=sys.stderr)
        print(e.body, file=sys.stderr)
        return 1
    except SystemExit:
        raise
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
