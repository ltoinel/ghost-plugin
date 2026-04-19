---
name: ghost
description: Interact with a Ghost CMS blog — list/read posts and publish or update posts from Markdown files — via the Ghost Admin API. Use this skill whenever the user mentions their Ghost blog, a Ghost CMS, "ghost.io", a .ghost domain, or asks to publish/draft/schedule/update/fetch blog posts in a context that involves Ghost. Trigger even when the user doesn't say "Ghost" explicitly if the context makes it clear (e.g., "publish this markdown as a draft on my blog" when prior turns established Ghost as their platform). Prefer this skill over writing raw API calls inline — it handles JWT auth, the markdown→HTML conversion, and the Ghost-specific update concurrency rules that are easy to get wrong.
---

# Ghost CMS

This skill helps you work with a Ghost blog through the **Ghost Admin API**. It ships a small Python CLI (`scripts/ghost.py`) that handles the annoying parts (JWT signing, markdown conversion, `updated_at` concurrency checks) so you can focus on the content.

## When to use this skill

Trigger whenever the user wants to read from or write to a Ghost blog. Common phrasings: "publish this post to my blog", "update the post titled X", "what's on my blog", "draft a post on Ghost", "schedule this for Friday". Even if the user just refers to "my blog" — if you have prior context that they use Ghost, use this skill.

Don't trigger for: WordPress, Medium, Substack, Wix, or any non-Ghost CMS. Don't trigger for writing or editing the post content itself in isolation — only when publishing/fetching/updating is part of the request.

## Setup the user must have done

The CLI reads credentials from environment variables:

- `GHOST_ADMIN_API_URL` — the blog's base URL, e.g. `https://example.ghost.io` (no trailing slash, no `/ghost/api/...` suffix)
- `GHOST_ADMIN_API_KEY` — the Admin API key from *Ghost Admin → Settings → Integrations → Add custom integration*. Format: `{id}:{secret}` (24-hex-char id, colon, 64-hex-char secret).

If either is missing, the CLI prints a clear error pointing to these variables. If the user hasn't set them yet, walk them through creating a custom integration in Ghost Admin and copying the Admin API key (not the Content API key — Admin is the one that starts with a 24-char hex id followed by a colon).

## How to use the CLI

Always prefer the bundled CLI over writing raw `requests`/`curl` calls. It handles auth, retries, request shape, and the `updated_at` concurrency rule.

All commands print JSON to stdout by default — parse or display as useful.

### List recent posts

```
python scripts/ghost.py list-posts [--limit N] [--status draft|published|scheduled|all] [--fields title,slug,status,published_at]
```

Default limit is 15. Use `--status all` to include drafts and scheduled.

### Get a single post

```
python scripts/ghost.py get-post <id-or-slug> [--include-html]
```

Accepts either the 24-hex post id or the slug (e.g. `hello-world`). Without `--include-html`, returns metadata only (fast, fewer tokens). With `--include-html`, includes the rendered HTML body.

### Create a post from a markdown file

```
python scripts/ghost.py create-post <markdown-file> \
    [--title "Title"] \
    [--status draft|published|scheduled] \
    [--tags tag1,tag2] \
    [--feature-image URL] \
    [--excerpt "Short summary"] \
    [--slug custom-slug] \
    [--publish-at 2026-05-01T09:00:00Z]
```

If `--title` is omitted, the script uses the first `# H1` heading from the markdown (and strips it from the body so it isn't duplicated). If there's no H1, it falls back to the filename.

`--status` defaults to `draft` — that's the safe default. Use `published` only when the user is explicit ("publish it live", "go live", "ship it"). Use `scheduled` with `--publish-at` for a future ISO-8601 timestamp.

The script prints the created post's `id`, `slug`, `status`, and full `url`. Share the url with the user so they can preview.

### Update an existing post

```
python scripts/ghost.py update-post <id-or-slug> \
    [--markdown FILE] \
    [--title "..."] \
    [--status draft|published|scheduled] \
    [--add-tags tag1,tag2] \
    [--set-tags tag1,tag2] \
    [--feature-image URL] \
    [--excerpt "..."] \
    [--publish-at 2026-05-01T09:00:00Z]
```

`--add-tags` appends to existing tags; `--set-tags` replaces them. Only the fields you pass get updated — everything else is left alone. The script handles the `updated_at` round-trip automatically (fetches current post, includes its `updated_at` in the PUT, retries once on conflict).

### Delete a post

```
python scripts/ghost.py delete-post <id-or-slug>
```

Prints `{"deleted": true, "id": "..."}` on success. No confirmation prompt — only run this when the user is unambiguous.

## Content format

- Users author in Markdown. The CLI converts markdown → HTML (using the `markdown` library, auto-installed on first use) and sends it to Ghost with `?source=html`. Ghost server-side converts HTML → its native Lexical format.
- Images in markdown (`![alt](url)`) pass through. Relative image paths won't work — use absolute URLs or upload the image first (not currently supported by this skill — tell the user to upload via Ghost Admin).
- Code fences, tables, and GFM extensions are supported via `markdown`'s `extra` + `tables` + `fenced_code` extensions.
- Frontmatter in the markdown file is parsed: if the file starts with `---`, everything between the `---` markers is treated as YAML metadata. Recognized keys: `title`, `tags`, `status`, `excerpt`, `slug`, `feature_image`, `publish_at`. Values from frontmatter are overridden by explicit CLI flags.

Example markdown with frontmatter:

```markdown
---
title: Release notes for v2.3
tags: [releases, engineering]
status: draft
excerpt: What shipped this sprint.
---

# Release notes for v2.3

We shipped three things this week...
```

## Common gotchas

**`updated_at` concurrency check.** Ghost rejects a PUT if the post's `updated_at` doesn't match what you sent — this protects against clobbering concurrent edits. The `update-post` command handles this transparently by fetching-then-PUT-ing. Don't write PUT requests manually; use the CLI.

**Tag creation is implicit.** When you create or update a post with a tag name that doesn't exist, Ghost creates it. If the user asks to rename or delete a tag itself (not on a post), that's a separate `/tags/` endpoint — not currently supported by this skill; fall back to a raw API call or tell the user to do it in Ghost Admin.

**Draft vs published.** Always default to `draft` unless the user explicitly says to publish. It's much easier to recover from an unpublished draft than from a post that went out to subscribers.

**`feature_image` is URL-only.** Ghost wants an absolute URL. The skill can't upload images for you; if the user has a local image, ask them to upload it to their blog (drag-drop into any Ghost editor works) and paste back the URL.

**Secret vs id in the Admin API key.** The key is `{id}:{secret}` — the id goes in the JWT `kid` header, the secret (hex-decoded) is the HMAC key. The CLI does this for you; don't try to pass the key as a bearer token.

## Research / reading posts

For queries like "find my post about X" or "what did I write about last month":

1. `list-posts --limit 50` to get recent metadata
2. Filter by title/tag/published_at client-side
3. If needed, `get-post <slug>` with `--include-html` to read the body of specific posts

Avoid `get-post --include-html` for every result — bodies are large and eat tokens.

## When the CLI isn't enough

For operations beyond posts (pages, members, tags management, themes, offers, tiers), the Admin API has parallel endpoints but this skill doesn't cover them yet. See `references/api_reference.md` for endpoint-level detail if you need to write a one-off curl command for an advanced operation. Mention to the user that broader coverage could be added to the skill.
