# notion-native-toolkit

Notion SDK for Python. Official API + internal API in one package.

## Why this exists

- One SDK to access both Notion's official API (v1) and internal API (v3).
- Official API covers pages, blocks, databases, comments, search-by-title.
- Internal API covers everything else: full-text search, AI execution, user/member management, guest invite flow, workspace analytics.
- Manage multiple workspaces with profiles, Keychain secret storage, and browser fallback.
- Reuse across projects instead of rebuilding Notion scripts.

## Architecture

```
NotionToolkit.from_profile("worxphere")
  .client     -> NotionApiClient     (official v1, Bearer token)
  .internal   -> NotionInternalClient (internal v3, token_v2 cookie)
  .browser    -> NotionBrowserAutomation (Playwright fallback)
  .writer     -> NotionWriter         (Markdown -> Notion blocks)
```

## Core capabilities

- **Official API client**: Pages, blocks, databases, comments, file uploads, markdown read/write.
- **Internal API client**: Full-text search, AI (streaming ndjson), user search, teams, permission groups, workspace usage, transaction-based mutations.
- **Multi-workspace profiles** with per-workspace API token, token_v2, workspace URL, page defaults, and browser session state.
- **Native macOS Keychain** secret storage for API tokens, login emails, and passwords.
- **Browser automation** for login, teamspace listing, teamspace creation, and Markdown paste fallback.
- **Markdown conversion**: Markdown to Notion blocks and back.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

## Quick start

Initialize config:

```bash
notion-native profile init
```

Create a workspace profile:

```bash
notion-native profile add team-a \
  --workspace-url https://www.notion.so/team-a \
  --parent-page-id 0123456789abcdef0123456789abcdef
```

Store the API token in macOS Keychain and bind it to the profile:

```bash
notion-native profile set-token team-a --value "ntn_xxx" --keychain
```

Store browser credentials:

```bash
notion-native profile set-browser-login team-a \
  --email user@example.com \
  --password "super-secret" \
  --keychain
```

Fetch a page as Markdown:

```bash
notion-native markdown from-page --profile team-a --page https://www.notion.so/... --output page.md
```

Create a page from Markdown:

```bash
notion-native page create-from-markdown \
  --profile team-a \
  --title "Spec" \
  --parent-page-id 0123456789abcdef0123456789abcdef \
  --file docs/spec.md
```

By default, the CLI prefers Notion's native markdown endpoints when available. Use block conversion explicitly when you need the custom block pipeline:

```bash
notion-native page update-from-markdown \
  --profile team-a \
  --page-id 0123456789abcdef0123456789abcdef \
  --file docs/spec.md \
  --mode blocks
```

Use browser fallback for unsupported actions:

```bash
notion-native browser login --profile team-a --headed
notion-native browser list-teamspaces --profile team-a
```

## Config model

The toolkit stores profiles in `~/.config/notion-native-toolkit/workspaces.json` by default.

Example structure:

```json
{
  "default_profile": "team-a",
  "profiles": {
    "team-a": {
      "workspace_url": "https://www.notion.so/team-a",
      "default_parent_page_id": "0123456789abcdef0123456789abcdef",
      "api_token": {
        "kind": "keychain",
        "service": "notion-native-toolkit",
        "account": "team-a.api_token"
      },
      "browser_email": {
        "kind": "keychain",
        "service": "notion-native-toolkit",
        "account": "team-a.browser_email"
      },
      "browser_password": {
        "kind": "keychain",
        "service": "notion-native-toolkit",
        "account": "team-a.browser_password"
      },
      "browser_state_path": "~/.config/notion-native-toolkit/browser-state/team-a.json"
    }
  }
}
```

## Project integration

Recommended usage in any project:

```bash
pip install notion-native-toolkit
```

For workspace-local development, an editable install also works:

```bash
pip install -e /path/to/notion-native-toolkit
```

Then call the shared CLI from the project, or import the package:

```python
from notion_native_toolkit import NotionToolkit

toolkit = NotionToolkit.from_profile("team-a")

# Official API (Bearer token)
page = toolkit.client.fetch_page("page-id")
rows = toolkit.client.query_database("db-id")

# Internal API (token_v2 cookie)
internal = toolkit.require_internal()

# Full-text search (richer than official API)
results = internal.search("meeting notes", limit=10)

# User/member search (for invite flows)
users = internal.list_users_search("kim")

# AI
models = internal.get_available_models()
usage = internal.get_ai_usage()
agents = internal.get_custom_agents()

# AI execution (streaming ndjson)
for chunk in internal.run_ai("Summarize this page", block_id="page-id"):
    print(chunk)

# Teams and workspace
teams = internal.get_teams()
groups = internal.get_permission_groups()
domains = internal.get_internal_domains()

# Content
backlinks = internal.get_backlinks("page-id")
lang = internal.detect_language("page-id")

# Write operations (transaction-based)
row_id = internal.create_db_row("collection-id", properties={"title": [["New Row"]]})
```

## Internal API setup

The internal client requires `token_v2` (browser session cookie) and `space_id`.

Get your token_v2 from Chrome DevTools > Application > Cookies > `token_v2`.
Get your space_id from any Notion API response or the URL after `notion.so/`.

Add to your workspace profile in `~/.config/notion-native-toolkit/workspaces.json`:

```json
{
  "profiles": {
    "team-a": {
      "workspace_url": "https://www.notion.so/team-a",
      "api_token": { "kind": "keychain", "service": "notion-native-toolkit", "account": "team-a.api_token" },
      "space_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "user_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "token_v2": { "kind": "env", "variable": "NOTION_TOKEN_V2" }
    }
  }
}
```

Note: `token_v2` is a browser session cookie that expires. Refresh it when integration tests start failing.

## Testing

```bash
# Unit tests (mocked, no API calls)
pytest tests/ -q -m "not integration"

# Integration tests (hits real Notion API, requires cookies)
pytest tests/test_internal_integration.py -v

# All tests
pytest tests/ -v
```

Integration tests serve as a change detector. If Notion changes their internal API, the failing tests tell you exactly which SDK methods broke.

## Shared guidance

- Centralized operating rules live in `docs/notion-toolkit-guidelines.md`.
- The bundled Claude skill lives in `.claude/skills/notion-native-toolkit/SKILL.md`.

## Available internal API methods

| Category | Methods |
|----------|---------|
| **Search** | `search(query)` |
| **Users** | `list_users_search(query)`, `find_user(email)`, `get_visible_users()`, `get_teams()`, `get_internal_domains()`, `get_member_email_domains()`, `get_permission_groups()` |
| **AI** | `run_ai(prompt)`, `get_available_models()`, `get_ai_usage()`, `get_custom_agents()`, `get_ai_connectors()`, `get_user_prompts()` |
| **Content** | `load_page_chunk(page_id)`, `get_backlinks(block_id)`, `detect_language(page_id)` |
| **Write** | `save_transactions(ops)`, `save_transactions_fanout(ops)`, `create_db_row(collection_id)` |
| **Workspace** | `get_space_usage()`, `get_bots()`, `search_integrations(query)` |

Full endpoint documentation: `docs/internal-api-capture.md`

## Notes

- Keep project-specific business logic in the consuming project; keep Notion I/O in this toolkit.
- The toolkit never commits secrets; use environment variables or Keychain references.
- Internal API endpoints are undocumented and may change without notice. Integration tests detect breakage.
- Browser selectors may need updates when Notion changes its UI.
- Browser commands can run from a profile without an API token; API and page commands require one.
