# Notion Toolkit Guidelines

This document centralizes the rules and patterns that were previously scattered across multiple projects in `/Users/seokmogu/project`.

## Scope

- Reuse this toolkit from new projects instead of creating one-off Notion scripts.
- Keep project-specific business workflows in the consuming project.
- Keep Notion API, browser automation, profile management, and Markdown conversion in this repo.

## Workspace Model

- Treat each Notion workspace as a separate profile with its own token and browser session state.
- Prefer a single workspace for one organization when relations, rollups, and linked database views must work together.
- Use multiple profiles when separate workspaces are unavoidable.

## Credentials

- Never commit tokens, passwords, cookies, or session files.
- Prefer macOS Keychain-backed profile credentials.
- Use environment variable references only when project deployment requires them.
- Rotate compromised credentials immediately.

## API First, Browser Second

- Use the Notion API for pages, blocks, databases, file uploads, comments, and users.
- Prefer the native Markdown endpoints for create, read, and replace when possible.
- Use browser automation only for unsupported UI workflows such as teamspace creation, linked view setup, or editor-only actions.

## Markdown Rules

- Default to native Markdown endpoints for round-trip workflows.
- Use the block conversion fallback for custom control or older endpoints.
- Preserve standard Markdown compatibility as the source format.
- Expect special handling for Notion-specific callouts, tables, page mentions, and list nesting limits.

## Sync Rules

- Preserve stable page ids when a consuming project needs durable mappings.
- Do not delete page mapping files or pages unless a workflow explicitly requires archival or trash behavior.
- Prefer update-in-place workflows over recreate-and-delete for stable URLs.

## Safety Rules

- Do not log PII or sensitive document contents.
- Keep rate limiting and retry behavior enabled for API calls.
- Preserve child pages during content replacement unless the caller explicitly opts out.

## Reuse Rules for New Projects

- Install with `pip install -e /Users/seokmogu/project/notion-native-toolkit`.
- Configure a profile instead of adding project-local Notion credentials logic.
- Call the CLI directly for simple automation.
- Import the Python package for richer application integration.
