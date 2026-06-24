# Official API Capture via ntn

`notion-native api capture` captures Notion's official CLI-visible API surface
into local files. Use it before adding or changing public API wrappers so the
code change is grounded in the current `ntn api ls/docs/spec` output.

This command does not write to Notion. It reads the CLI API index and optional
endpoint docs/spec fragments.

## Capture the Index

```bash
notion-native api capture \
  --output-dir docs/notion-api-capture/current
```

Outputs:

- `api-index.json`
- `manifest.json`

## Compare Captures

```bash
notion-native api diff \
  --old-dir docs/notion-api-capture/current \
  --new-dir docs/notion-api-capture/2026-06-23
```

The command prints JSON with `added`, `removed`, and `changed` endpoint lists.
It exits with `1` when differences are found and `0` when the indexes match, so
it can be used as a drift detector in review scripts.

## Capture Endpoint Docs and Specs

```bash
notion-native api capture \
  --profile worxphere \
  --output-dir docs/notion-api-capture/2026-06-23 \
  --endpoint POST:v1/comments \
  --endpoint PATCH:v1/pages/{page_id}
```

Outputs:

- `api-index.json`
- `docs/<method>-<path>.md`
- `specs/<method>-<path>.json` or `.txt`
- `manifest.json`

`--profile` is optional. When present, the profile API token is forwarded to
`ntn` as `NOTION_API_TOKEN`. When omitted, `ntn` uses its own authentication
state and environment variables.

## When to Use

- Before adopting a newly exposed official endpoint.
- Before replacing a custom HTTP wrapper with an `ntn`-aligned implementation.
- When a public API wrapper starts failing and the current official spec is
  needed for comparison.

## Current Baseline

`docs/notion-api-capture/current` was captured from `ntn 0.17.0` and includes:

- API index: 44 endpoints
- Blocks: retrieve, update, delete, children retrieve/append, and meeting notes query
- Pages: create, retrieve, update, move, and Markdown retrieve/update endpoints
- Page properties: retrieve property item endpoint
- Databases: create, retrieve, and update endpoints
- Comments: list, create, retrieve, update, and delete endpoints
- File uploads: list, create, retrieve, upload, and multipart completion
- Data sources: create, retrieve, update, query, and template listing endpoints
- Search, users, and custom emojis: read-oriented public endpoints
- Views: list, create, retrieve, update, delete, query create/results/delete
