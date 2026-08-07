# Notion Toolkit Guidelines

The workspace-wide source of truth is `/Users/seokmogu/project/NOTION_PUBLISHING.md`. This document defines how `notion-native-toolkit` supports that policy.

## Role

This toolkit is an adapter over official Notion surfaces, not the default interactive integration.

- Use hosted Notion MCP for interactive search, fetch, page/database updates, comments, and recent-page discovery.
- Use official enhanced Markdown endpoints through `notion-native` for deterministic create/read/update, batch, and headless workflows.
- Use toolkit-specific logic only for hierarchy, stable mappings, child-page preservation, files, profiles, dry-run/diff/rollback evidence, or a named official-surface gap.
- Keep internal API and browser automation opt-in. Document the missing official capability before selecting either.

## Markdown

- Prefer native enhanced Markdown round-trips.
- Strip a leading H1 that matches the Notion page title.
- Do not inject empty paragraphs after headings, callouts, code, tables, or lists.
- Treat `<empty-block/>` as an explicit source instruction, never an automatic spacing rule.
- Use `<br>` only for intentional hard breaks inside one paragraph.
- Preserve child pages and databases by default.

The custom block converter is a compatibility fallback. A caller that selects it must test the exact unsupported feature and verify the resulting block sequence.

## Profiles and Credentials

- Keep each workspace in a separate profile.
- Prefer Keychain or environment-variable references for official API credentials.
- Never store tokens, cookies, passwords, or session state in `.mcp.json`, project config, scripts, skills, or documentation.
- Hosted MCP authentication belongs to the MCP client's OAuth flow.

## Safety and Evidence

Read-only exports and inspections may run directly. Writes require the workspace sequence: fresh export, local diff/dry-run, exact target/scope approval, apply, fresh export verification.

Preserve stable page IDs and mapping files. Do not delete or recreate pages to simplify deployment. Store durable rollback and verification evidence in the consuming project's dated evidence/operations area.

## Reuse

- Call `notion-native` for simple automation.
- Import the Python package for a real application integration.
- Keep project business logic in the consuming project.
- Do not create another project-local Markdown uploader or Notion client wrapper.
