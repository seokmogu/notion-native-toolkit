---
name: notion-native-toolkit
description: Reusable native Notion toolkit for multi-workspace API access, browser fallback automation, and Markdown round-trip workflows. Use when a project needs Notion support without creating a new one-off tool.
---

# notion-native-toolkit

Use this shared toolkit instead of building a fresh Notion integration in each project.

## Use cases

- Multi-workspace token and browser credential management
- Fetching or updating pages and databases through the Notion API
- Browser fallback for teamspaces or other UI-only tasks
- Markdown to Notion or Notion to Markdown conversion
- Shared project automation that should be installable from the workspace root

## Install

```bash
pip install notion-native-toolkit
playwright install chromium
```

## Common commands

```bash
notion-native profile init
notion-native profile add my-workspace --workspace-url https://www.notion.so/my-workspace
notion-native profile set-token my-workspace --value "ntn_xxx" --keychain
notion-native markdown from-page --profile my-workspace --page https://www.notion.so/... --output page.md
notion-native page create-from-markdown --profile my-workspace --title "Spec" --parent-page-id PAGE_ID --file spec.md
notion-native browser login --profile my-workspace --headed
```

## Rules

- Keep secrets in env vars or macOS Keychain, never in committed files.
- Keep project-specific business workflows outside the toolkit.
- Prefer API operations first; use browser automation only for unsupported UI features.
- Preserve stable page ids and mappings in the consuming project when sync workflows depend on them.
