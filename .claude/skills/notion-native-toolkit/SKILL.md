---
name: notion-native-toolkit
description: Use notion-native-toolkit for deterministic official Notion Markdown/API work, hierarchical deployment, mappings, child-page preservation, files, profiles, or an explicitly identified hosted-MCP gap. Do not use it as the default interactive Notion integration; hosted Notion MCP remains primary for search, fetch, and narrow edits.
---

# notion-native-toolkit

Read `/Users/seokmogu/project/NOTION_PUBLISHING.md` and `docs/notion-toolkit-guidelines.md` completely.

Route interactive search/fetch and narrow edits to hosted Notion MCP. Use this toolkit for official enhanced Markdown batch/headless work or support features such as hierarchy, `page_mapping.json`, child preservation, file uploads, profiles, and durable deployment evidence.

Prefer `--mode native` for leaf pages. Use custom block conversion only for a tested unsupported case or child-preserving workflow. Never inject automatic empty paragraphs after headings, duplicate the page title as an H1, or use `<br>` for incidental source newlines.

Internal API/MCP and browser automation are opt-in fallbacks. State the missing official capability before using them.

All writes follow the workspace fresh-export/diff/approval/apply/fresh-export gate. Keep secrets in Keychain or environment variables and never in MCP JSON, skill text, scripts, or command arguments.
