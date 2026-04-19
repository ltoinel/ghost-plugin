# Ghost Plugin for Claude

Lets Claude read from and publish to your [Ghost](https://ghost.org) blog via the Admin API.

Once installed, you can ask Claude things like:

- *"List the 5 most recent posts on my Ghost blog."*
- *"Publish release-notes.md to my Ghost blog as a draft."*
- *"Add the announcements tag to the hello-world post."*

## Install

Drag `ghost.plugin` into **Cowork** (desktop app) or **Claude Code** — a card appears with an **Install** button.

Then export your Ghost credentials in the shell where Claude runs:

```bash
export GHOST_ADMIN_API_URL=https://yourblog.ghost.io
export GHOST_ADMIN_API_KEY=<key_id>:<secret_hex>
```

Get the key from **Ghost Admin → Settings → Integrations → Add custom integration** and copy the **Admin API Key** (not the Content API key).

## What's inside

A single skill, `ghost`, with a bundled Python CLI (`scripts/ghost.py`) that handles the parts that are easy to get wrong:

- HS256 JWT authentication for the Admin API
- Markdown-with-frontmatter → HTML conversion via `?source=html`
- The `updated_at` optimistic-concurrency rule on PUT (409 retries)
- Subcommands: `list-posts`, `get-post`, `create-post`, `update-post`, `delete-post`

## Repository layout

```
ghost-plugin/
├── .claude-plugin/plugin.json   ← plugin manifest
├── skills/ghost/
│   ├── SKILL.md                 ← what Claude reads
│   ├── scripts/ghost.py         ← stdlib-only Python CLI
│   ├── references/api_reference.md
│   └── evals/                   ← 3 test scenarios
├── ghost.plugin                 ← built, ready-to-install
└── README.md
```

## Rebuilding `ghost.plugin`

After editing anything under the repo, rebuild the distributable:

```bash
zip -r ghost.plugin . -x "ghost.plugin" "*.DS_Store" "*.pyc" "__pycache__/*" ".git/*"
```

## Verification

Ask Claude *"list the 5 most recent posts on my Ghost blog"*. Claude should invoke the skill and run `ghost.py list-posts --limit 5`.
