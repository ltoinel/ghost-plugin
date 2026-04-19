# Ghost Admin API — quick reference

Only read this file if the bundled CLI doesn't cover what you need (e.g., pages, members, tags management) and you're about to write a one-off request.

## Base URL

```
{GHOST_ADMIN_API_URL}/ghost/api/admin/{resource}/
```

Set `Accept-Version: v5.0` and `Authorization: Ghost {jwt}`.

## JWT

- `alg`: HS256
- `typ`: JWT
- `kid`: the id part of the admin key (24 hex chars)
- Payload: `{iat, exp, aud: "/admin/"}`, exp ≤ 5 minutes from iat
- Signing key: `bytes.fromhex(secret_part_of_admin_key)`

See `make_jwt` in `scripts/ghost.py` for a stdlib-only implementation.

## Posts

- `GET /posts/?limit=15&order=published_at+desc&filter=status:draft&fields=id,title,slug`
- `GET /posts/{id}/`
- `GET /posts/slug/{slug}/`
- `POST /posts/?source=html` — body: `{"posts": [{"title": "...", "html": "..."}]}`
- `PUT /posts/{id}/?source=html` — body must include `updated_at` from the last GET
- `DELETE /posts/{id}/` — returns 204 with empty body

### Post object (most useful fields)

```
id, uuid, title, slug, html, lexical, mobiledoc
status: draft | published | scheduled | sent
visibility: public | members | paid | tiers
feature_image, feature_image_alt, feature_image_caption
excerpt, custom_excerpt
tags: [{name, slug, ...}]
authors: [{id, name, slug, ...}]
published_at, created_at, updated_at   # ISO-8601, UTC
url
og_image, og_title, og_description     # social cards
meta_title, meta_description           # SEO
```

### Concurrency

Ghost uses `updated_at` as an optimistic lock. Any `PUT` that sends an `updated_at` older than what the server has returns `409`. Always GET → modify → PUT using the server's most recent `updated_at`.

### Sending content

- `?source=html` — Ghost converts the provided `html` to its native Lexical format server-side. Simplest path for markdown-authored content.
- Omit `?source=html` and send `lexical` (JSON string) for full-fidelity editor features like callouts, bookmarks, embeds, galleries.
- `mobiledoc` is the legacy format — still accepted but being phased out; avoid for new posts.

## Pages

Same shape as Posts but at `/pages/`. No `published_at` scheduling semantics; static.

## Tags

- `GET /tags/`
- `GET /tags/slug/{slug}/`
- `POST /tags/` — body: `{"tags": [{"name": "..."}]}`
- `PUT /tags/{id}/` — same `updated_at` rule
- `DELETE /tags/{id}/`

Tags on a post can be attached implicitly by including them in the post body; the tag doesn't need to exist first.

## Members

- `GET /members/?limit=15`
- `POST /members/` — `{"members": [{"email": "...", "name": "...", "labels": [...]}]}`
- `PUT /members/{id}/`
- `DELETE /members/{id}/`

## Images

- `POST /images/upload/` with multipart form data (`file` part + optional `purpose` = `image|profile_image|icon`)
- Returns `{"images": [{"url": "https://..."}]}` — paste the URL into a post's `feature_image` or `<img src=...>` in HTML.

## Webhooks, themes, offers, tiers

All have parallel REST endpoints under `/ghost/api/admin/`. Consult the official docs at ghost.org/docs/admin-api for schemas when needed.

## Errors

- `401` — JWT invalid or expired. Regenerate per request (the CLI already does).
- `404` — resource not found. Check id/slug.
- `409` — `updated_at` conflict on update. Refetch and retry.
- `422` — validation error (often missing required fields like `title`). Body includes `errors[].message` with specifics.
