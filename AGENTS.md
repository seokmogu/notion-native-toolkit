# AGENTS.md — Notion Native Toolkit

The workspace-wide authority is [`../AGENTS.md`](../AGENTS.md). For every Notion inspection, styling, or publishing task, also follow [`../NOTION_PUBLISHING.md`](../NOTION_PUBLISHING.md).

## Tool role

- Prefer Hosted Notion MCP for interactive search, fetch, and narrow edits.
- Prefer Notion's official enhanced Markdown/API through `notion-native` for batch, repeatable, or headless publishing.
- Use this toolkit's custom hierarchy, mapping, child-preservation, file, profile, evidence, internal API, or browser features only when the required capability is not supported by the official surface.
- Do not add another one-off uploader or make a custom block writer the default path.

## Publishing and style contract

- A Notion write requires the workspace write-safety gate and exact approval for the current target and scope.
- Existing pages follow fresh export, local diff/dry-run, approval, apply, and fresh export verification.
- Prefer native Markdown for leaf-page content.
- Remove a first H1 when it duplicates the Notion page title.
- Do not insert empty paragraphs automatically after headings, callouts, or code blocks.
- Use `<empty-block/>` only for an intentional blank Notion block and `<br>` only for an intentional hard line break inside one block.
- Preserve rollback evidence for managed documentation sets.

## Verification

Run the smallest targeted tests first, then the relevant lint and type checks. For publishing behavior, verify dry-run output and fresh exports; never treat a successful request alone as proof of correct structure or styling.
