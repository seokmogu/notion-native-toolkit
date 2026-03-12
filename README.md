# notion-native-toolkit

Reusable Notion toolkit for multi-workspace API access, browser fallback automation, and Markdown round-trips.

## Why this exists

- Manage multiple Notion workspaces and tokens from one shared toolkit.
- Reuse one installable package across projects instead of rebuilding Notion scripts.
- Use the API for supported operations and Playwright for browser-only workflows.
- Convert Markdown to Notion blocks and back with one code path.
- Expose both a CLI tool and a Claude skill entrypoint.

## Core capabilities

- Multi-workspace profiles with per-workspace API token, workspace URL, page defaults, and browser session state.
- Native macOS Keychain secret storage for API tokens, login emails, and passwords.
- HTTP API client with pagination, retry, rate limiting, block append chunking, and file upload support.
- Browser automation for login, teamspace listing, teamspace creation, and Markdown paste fallback.
- Markdown to Notion and Notion to Markdown conversion helpers.

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
from notion_native_toolkit.toolkit import NotionToolkit

toolkit = NotionToolkit.from_profile("team-a")
page = toolkit.client.fetch_page("0123456789abcdef0123456789abcdef")
```

## Shared guidance

- Centralized operating rules live in `docs/notion-toolkit-guidelines.md`.
- The bundled Claude skill lives in `.claude/skills/notion-native-toolkit/SKILL.md`.

## Notes

- Keep project-specific business logic in the consuming project; keep Notion I/O in this toolkit.
- The toolkit never commits secrets; use environment variables or Keychain references.
- Browser selectors may need updates when Notion changes its UI.
- Browser commands can run from a profile without an API token; API and page commands require one.
