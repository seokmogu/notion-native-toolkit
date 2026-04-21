"""Notion Internal API client (v3).

Provides access to Notion features not available through the official API.
Uses browser session cookies (token_v2) for authentication.

Warning: These are undocumented, internal endpoints. They may change without notice.
         Use official API endpoints (NotionApiClient) whenever possible.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from typing import Any, Iterator

import httpx

logger = logging.getLogger(__name__)

INTERNAL_BASE_URL = "https://www.notion.so/api/v3/"


class NotionInternalClient:
    """Client for Notion's internal /api/v3/ endpoints."""

    def __init__(
        self,
        token_v2: str,
        space_id: str,
        user_id: str | None = None,
        rate_limit: float = 0.35,
        timeout: float = 30.0,
    ) -> None:
        self.token_v2 = token_v2
        self.space_id = space_id
        self.user_id = user_id
        self.rate_limit = rate_limit
        self.timeout = timeout
        verify_ssl = not bool(os.getenv("NO_SSL_VERIFY"))
        self._session = httpx.Client(
            base_url=INTERNAL_BASE_URL,
            timeout=timeout,
            verify=verify_ssl,
            cookies={"token_v2": token_v2},
            headers={
                "Content-Type": "application/json",
                "x-notion-active-user-header": user_id or "",
                "x-notion-space-id": space_id,
            },
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> NotionInternalClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- Low-level request ---

    def _post(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
        retries: int = 3,
    ) -> dict[str, Any] | None:
        """POST to /api/v3/{endpoint} with retry and rate limiting."""
        backoffs = [1.5, 3.0, 6.0]
        for attempt in range(retries + 1):
            time.sleep(self.rate_limit)
            try:
                resp = self._session.post(endpoint, json=data or {})
            except httpx.HTTPError as exc:
                logger.warning("Request failed: %s %s", endpoint, exc)
                if attempt < retries:
                    time.sleep(backoffs[attempt])
                    continue
                return None

            if resp.status_code == 429 and attempt < retries:
                delay = float(resp.headers.get("Retry-After", backoffs[attempt]))
                logger.info("Rate limited on %s, retrying in %.1fs", endpoint, delay)
                time.sleep(delay)
                continue

            if resp.status_code >= 400:
                logger.warning(
                    "HTTP %d on %s: %s", resp.status_code, endpoint, resp.text[:200]
                )
                return None

            return resp.json()  # type: ignore[no-any-return]
        return None

    def _post_stream(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """POST and yield ndjson lines (for streaming endpoints like AI)."""
        time.sleep(self.rate_limit)
        verify_ssl = not bool(os.getenv("NO_SSL_VERIFY"))
        with httpx.Client(timeout=self.timeout, verify=verify_ssl) as client:
            with client.stream(
                "POST",
                f"{INTERNAL_BASE_URL}{endpoint}",
                json=data or {},
                cookies={"token_v2": self.token_v2},
                headers={
                    "Content-Type": "application/json",
                    "x-notion-active-user-header": self.user_id or "",
                    "x-notion-space-id": self.space_id,
                },
            ) as resp:
                if resp.status_code >= 400:
                    logger.warning("Stream HTTP %d on %s", resp.status_code, endpoint)
                    return
                import json

                for line in resp.iter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except Exception:
                        logger.debug("Non-JSON stream line: %s", line[:100])

    # --- Search ---

    def search(
        self,
        query: str,
        limit: int = 20,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Full-text search across workspace (richer than official API)."""
        payload: dict[str, Any] = {
            "type": "BlocksInSpace",
            "query": query,
            "limit": limit,
            "source": "quick_find",
            "spaceId": self.space_id,
            "sort": {"field": "relevance"},
            "filters": filters or {
                "isDeletedOnly": False,
                "excludeTemplates": False,
                "navigableBlockContentOnly": False,
                "requireEditPermissions": False,
                "ancestors": [],
                "createdBy": [],
                "editedBy": [],
                "lastEditedTime": {},
                "createdTime": {},
                "inTeams": [],
                "contentStatusFilter": "all_without_archived",
            },
        }
        return self._post("search", payload)

    # --- Users & Members ---

    def list_users_search(
        self,
        query: str,
        limit: int = 10,
    ) -> dict[str, Any] | None:
        """Search users by name or email (used in share/invite flow)."""
        return self._post("listUsers", {
            "limit": limit,
            "query": query,
            "spaceId": self.space_id,
            "includeAliasSearch": True,
        })

    def find_user(self, email: str) -> dict[str, Any] | None:
        """Find a Notion user by exact email (external user lookup).

        Note: This endpoint may require specific auth context and can fail
        with 400 for internal workspace members. For searching members,
        use list_users_search() instead which supports name and email queries.
        """
        return self._post("findUser", {"email": email})

    def get_visible_users(self) -> dict[str, Any] | None:
        """Get all visible users in the workspace."""
        return self._post("getVisibleUsers", {
            "spaceId": self.space_id,
            "supportsEdgeCache": True,
            "earlyReturnForEdgeCache": True,
        })

    def get_teams(
        self,
        team_types: list[str] | None = None,
    ) -> dict[str, Any] | None:
        """Get teams in workspace."""
        return self._post("getTeamsV2", {
            "spaceId": self.space_id,
            "teamTypes": team_types or ["Joined"],
            "includeMembershipSummary": False,
        })

    def get_internal_domains(self) -> dict[str, Any] | None:
        """Get internal (trusted) email domains."""
        return self._post("getInternalDomains", {"spaceId": self.space_id})

    def get_member_email_domains(self) -> dict[str, Any] | None:
        """Get email domains of current members."""
        return self._post("getMemberEmailDomains", {"spaceId": self.space_id})

    def get_permission_groups(self) -> dict[str, Any] | None:
        """Get all permission groups with member counts."""
        return self._post(
            "getAllSpacePermissionGroupsWithMemberCount",
            {"spaceId": self.space_id},
        )

    # --- AI ---

    def get_available_models(self) -> dict[str, Any] | None:
        """Get AI models available for the workspace."""
        return self._post("getAvailableModels", {"spaceId": self.space_id})

    def get_ai_usage(self) -> dict[str, Any] | None:
        """Get AI usage and credit limits."""
        return self._post("getAIUsageEligibilityV2", {"spaceId": self.space_id})

    def get_custom_agents(self) -> dict[str, Any] | None:
        """Get custom AI agents in workspace."""
        return self._post("getCustomAgents", {
            "spaceId": self.space_id,
            "filter": "all",
            "includeDeleted": False,
        })

    def get_ai_connectors(self) -> dict[str, Any] | None:
        """Get AI connector integrations (Slack, Calendar, etc.)."""
        return self._post("listAIConnectors", {"spaceId": self.space_id})

    def get_user_prompts(self) -> dict[str, Any] | None:
        """Get user's saved AI prompts."""
        return self._post("getUserPromptsInSpace", {"spaceId": self.space_id})

    def run_ai(
        self,
        prompt: str,
        block_id: str | None = None,
        thread_id: str | None = None,
        agent_name: str = "AI",
    ) -> Iterator[dict[str, Any]]:
        """Run Notion AI and stream the response (ndjson).

        Args:
            prompt: The user prompt text.
            block_id: Current page/block context for the AI.
            thread_id: Existing thread ID to continue, or None for new.
            agent_name: Display name for the AI agent.

        Yields:
            Parsed ndjson objects from the streaming response.
        """
        import datetime

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        tid = thread_id or str(uuid.uuid4())

        transcript: list[dict[str, Any]] = [
            {
                "id": str(uuid.uuid4()),
                "type": "config",
                "value": {
                    "type": "workflow",
                    "enableScriptAgent": True,
                    "enableAgentIntegrations": True,
                    "enableCustomAgents": True,
                    "enableAgentDiffs": True,
                    "useWebSearch": True,
                    "writerMode": False,
                    "isCustomAgent": False,
                    "isMobile": False,
                    "searchScopes": [{"type": "everything"}],
                },
            },
            {
                "id": str(uuid.uuid4()),
                "type": "context",
                "value": {
                    "timezone": "Asia/Seoul",
                    "userId": self.user_id or "",
                    "spaceId": self.space_id,
                    "currentDatetime": now,
                    "surface": "workflows",
                    "blockId": block_id or "",
                    "agentName": agent_name,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "type": "user",
                "value": [[prompt]],
                "userId": self.user_id or "",
                "createdAt": now,
            },
        ]

        payload: dict[str, Any] = {
            "traceId": str(uuid.uuid4()),
            "spaceId": self.space_id,
            "transcript": transcript,
            "threadId": tid,
            "threadParentPointer": {
                "table": "space",
                "id": self.space_id,
                "spaceId": self.space_id,
            },
            "createThread": thread_id is None,
            "generateTitle": True,
            "threadType": "workflow",
            "asPatchResponse": True,
        }

        yield from self._post_stream("runInferenceTranscript", payload)

    # --- Content ---

    def load_page_chunk(
        self,
        page_id: str,
    ) -> dict[str, Any] | None:
        """Load full page content via internal chunked loader."""
        return self._post("loadCachedPageChunkV2", {
            "page": {"id": page_id},
            "cursor": {"stack": []},
            "verticalColumns": False,
        })

    def get_backlinks(self, block_id: str) -> dict[str, Any] | None:
        """Get pages that link to this block."""
        return self._post("getBacklinksForBlockInitial", {
            "block": {"id": block_id},
        })

    def detect_language(self, page_id: str) -> dict[str, Any] | None:
        """Detect the language of a page's content."""
        return self._post("detectPageLanguage", {
            "pagePointer": {
                "id": page_id,
                "table": "block",
                "spaceId": self.space_id,
            },
        })

    # --- Transactions (write operations) ---

    def save_transactions(
        self,
        operations: list[dict[str, Any]],
        user_action: str = "sdk",
    ) -> dict[str, Any] | None:
        """Execute write operations via saveTransactionsMain.

        Use for structural changes: creating blocks, setting properties,
        changing parents. For text edits, use save_transactions_fanout.
        """
        return self._post("saveTransactionsMain", {
            "requestId": str(uuid.uuid4()),
            "transactions": [{
                "id": str(uuid.uuid4()),
                "spaceId": self.space_id,
                "debug": {"userAction": user_action},
                "operations": operations,
            }],
        })

    def save_transactions_fanout(
        self,
        operations: list[dict[str, Any]],
        user_action: str = "sdk",
    ) -> dict[str, Any] | None:
        """Execute content mutations via saveTransactionsFanout.

        Use for text edits, incremental content changes, lock/unlock.
        """
        return self._post("saveTransactionsFanout", {
            "requestId": str(uuid.uuid4()),
            "transactions": [{
                "id": str(uuid.uuid4()),
                "spaceId": self.space_id,
                "debug": {"userAction": user_action},
                "operations": operations,
            }],
        })

    # --- Workspace ---

    def get_space_usage(self) -> dict[str, Any] | None:
        """Get block usage stats for the workspace."""
        return self._post("getSpaceBlockUsage", {"spaceId": self.space_id})

    def get_bots(self) -> dict[str, Any] | None:
        """Get integration bots connected to workspace."""
        return self._post("getBots", {"spaceId": self.space_id})

    def search_integrations(
        self,
        query: str = "",
        integration_type: str = "compliance",
    ) -> dict[str, Any] | None:
        """Search available integrations."""
        return self._post("searchIntegrations", {
            "query": query,
            "type": integration_type,
            "spaceId": self.space_id,
        })

    # --- Convenience: high-level operations ---

    def create_db_row(
        self,
        collection_id: str,
        properties: dict[str, Any] | None = None,
    ) -> str | None:
        """Create a new row in a database collection.

        Returns the new page/block ID, or None on failure.
        """
        block_id = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)
        ops: list[dict[str, Any]] = [
            {
                "command": "set",
                "pointer": {
                    "table": "block",
                    "id": block_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "args": {
                    "id": block_id,
                    "type": "page",
                    "properties": properties or {"title": []},
                    "space_id": self.space_id,
                    "created_time": now_ms,
                    "created_by_table": "notion_user",
                    "created_by_id": self.user_id,
                    "last_edited_time": now_ms,
                },
            },
            {
                "command": "setParent",
                "pointer": {
                    "table": "block",
                    "id": block_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "args": {
                    "parentId": collection_id,
                    "parentTable": "collection",
                },
            },
        ]
        result = self.save_transactions(ops, user_action="sdk.createDbRow")
        return block_id if result is not None else None

    # --- Database Automations ---

    def _resolve_collection_id(self, database_id: str) -> str:
        """Resolve a DB identifier to its collection ID.

        Notion databases have two IDs: a block id (visible in URLs) and an
        underlying collection id where automations actually live. Accepts
        either; returns the collection id.
        """
        # Try as a collection first.
        resp = self._post(
            "syncRecordValuesMain",
            {
                "requests": [
                    {
                        "pointer": {
                            "id": database_id,
                            "table": "collection",
                            "spaceId": self.space_id,
                        },
                        "version": -1,
                    }
                ]
            },
        ) or {}
        entry = (
            (resp.get("recordMap") or {}).get("collection") or {}
        ).get(database_id) or {}
        if (entry.get("value") or {}).get("value"):
            return database_id

        # Fall back to resolving via block.
        resp = self._post(
            "syncRecordValuesMain",
            {
                "requests": [
                    {
                        "pointer": {
                            "id": database_id,
                            "table": "block",
                            "spaceId": self.space_id,
                        },
                        "version": -1,
                    }
                ]
            },
        ) or {}
        block_entry = (
            (resp.get("recordMap") or {}).get("block") or {}
        ).get(database_id) or {}
        block_value = (block_entry.get("value") or {}).get("value") or {}
        cid = (
            block_value.get("collection_id")
            or (block_value.get("format") or {})
            .get("collection_pointer", {})
            .get("id")
        )
        if not cid:
            raise ValueError(
                f"Could not resolve collection id from {database_id!r}"
            )
        return cid

    def list_database_automations(
        self,
        database_id: str,
    ) -> list[dict[str, Any]]:
        """Return automation records attached to a database.

        ``database_id`` may be a block id (URL form) or a collection id.
        Reads ``collection.format.automation_ids`` then fetches each
        automation record via ``syncRecordValuesSpaceInitial``.
        """
        collection_id = self._resolve_collection_id(database_id)
        coll_resp = self._post(
            "syncRecordValuesMain",
            {
                "requests": [
                    {
                        "pointer": {
                            "id": collection_id,
                            "table": "collection",
                            "spaceId": self.space_id,
                        },
                        "version": -1,
                    }
                ]
            },
        ) or {}
        record_map = coll_resp.get("recordMap", {}) or {}
        coll_entry = (record_map.get("collection") or {}).get(collection_id) or {}
        coll_value = (coll_entry.get("value") or {}).get("value") or {}
        automation_ids: list[str] = (
            (coll_value.get("format") or {}).get("automation_ids") or []
        )

        out: list[dict[str, Any]] = []
        for aid in automation_ids:
            resp = self._post(
                "syncRecordValuesMain",
                {
                    "requests": [
                        {
                            "pointer": {
                                "id": aid,
                                "table": "automation",
                                "spaceId": self.space_id,
                            },
                            "version": -1,
                        }
                    ]
                },
            ) or {}
            rm = resp.get("recordMap", {}) or {}
            entry = (rm.get("automation") or {}).get(aid) or {}
            val = (entry.get("value") or {}).get("value") or {}
            if val:
                out.append(val)
        return out

    def create_database_webhook_automation(
        self,
        database_id: str,
        webhook_url: str,
        *,
        name: str | None = None,
        trigger: str = "pages_added",
        api_version: str = "2026-03-11",
    ) -> str | None:
        """Create a DB automation that POSTs to ``webhook_url`` on a trigger.

        Args:
            database_id: Collection (database) UUID.
            webhook_url: HTTP(S) endpoint to receive the webhook POST.
            name: Optional automation name; Notion defaults it otherwise.
            trigger: One of ``"pages_added"`` (default: fires on new page)
                or ``"page_props_any"`` (fires on any property edit).
            api_version: ``config.apiVersion`` field sent with the action.

        Returns: The new automation UUID, or None on failure.
        """
        # @MX:NOTE: Payload shape captured from Notion's web client
        # (collectionSettingsAutomationsActions.createDatabaseAutomation).
        # Requires the metadata update ops at the end — Notion validates
        # automation.last_edited_by_id matches the request's actor.
        collection_id = self._resolve_collection_id(database_id)
        automation_id = str(uuid.uuid4())
        action_id = str(uuid.uuid4())
        trigger_uuid = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)

        collection_ptr = {
            "id": collection_id,
            "table": "collection",
            "spaceId": self.space_id,
        }
        event: dict[str, Any] = {
            "pagesAdded": trigger == "pages_added",
            "pagePropertiesEdited": (
                {"type": "any"} if trigger == "page_props_any"
                else {"type": "none"}
            ),
            "source": {"pointer": collection_ptr, "type": "collection"},
        }
        properties = {"name": name} if name else {}

        ops: list[dict[str, Any]] = [
            {
                "pointer": collection_ptr,
                "path": ["format", "automation_ids"],
                "command": "listAfter",
                "args": {"id": automation_id},
            },
            {
                "pointer": {
                    "table": "automation_action",
                    "id": action_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "set",
                "args": {
                    "id": action_id,
                    "type": "http_request",
                    "parent_id": automation_id,
                    "parent_table": "automation",
                    "alive": True,
                    "space_id": self.space_id,
                    "config": {
                        "apiVersion": api_version,
                        "url": webhook_url,
                    },
                    "blocks": [],
                },
            },
            {
                "pointer": {
                    "id": automation_id,
                    "table": "automation",
                    "spaceId": self.space_id,
                },
                "path": ["action_ids"],
                "command": "listAfter",
                "args": {"id": action_id},
            },
            {
                "pointer": {
                    "table": "automation",
                    "id": automation_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "set",
                "args": {
                    "action_ids": [action_id],
                    "alive": True,
                    "id": automation_id,
                    "parent_id": collection_id,
                    "parent_table": "collection",
                    "properties": properties,
                    "space_id": self.space_id,
                    "status": "active",
                    "trigger": {
                        "id": trigger_uuid,
                        "type": "event",
                        "event": event,
                    },
                },
            },
            # Metadata ops: Notion rejects with "last_edited_by is not the actor"
            # unless the collection + automation carry the current user id.
            {
                "pointer": collection_ptr,
                "path": [],
                "command": "update",
                "args": {
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            },
            {
                "pointer": {
                    "table": "automation",
                    "id": automation_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "created_by_id": self.user_id,
                    "created_by_table": "notion_user",
                    "created_time": now_ms,
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            },
        ]
        # Optional: update the DB block's last_edited too (if caller passed a
        # block id, not a collection id). Harmless when database_id == collection_id.
        if database_id != collection_id:
            ops.append({
                "pointer": {
                    "table": "block",
                    "id": database_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            })
        result = self.save_transactions_fanout(
            ops, user_action="sdk.createDatabaseAutomation",
        )
        return automation_id if result is not None else None

    def create_database_add_page_automation(
        self,
        source_database_id: str,
        target_database_id: str,
        *,
        title_text: str = "자동 생성",
        selects: dict[str, str] | None = None,
        source_refs: dict[str, tuple[str, str]] | None = None,
        formula_refs: dict[str, tuple[str, str, str]] | None = None,
        trigger_page_refs: list[str] | None = None,
        name: str | None = None,
        trigger: str = "pages_added",
        prop_filters: list[dict[str, Any]] | None = None,
    ) -> str | None:
        """Create a DB automation that adds a page to another database.

        Mirrors the UI flow: ⚡ → 새 작업 → 페이지 추가 위치 → pick target DB →
        set title text → 활성화. Supports literal Title and Select property
        mappings. References to source-row properties (People / Relation /
        copy from source) are NOT yet supported — configure those via
        Notion's Automation UI after creation.

        Args:
            source_database_id: Source DB (trigger DB) — block or collection id.
            target_database_id: Target DB where the new page is created.
            title_text: Literal text written to the target page's title column.
            selects: Optional ``{property_id: option_name}`` dict for literal
                Select option assignments on the target page (e.g.,
                ``{"hcOM": "신청중"}``). Property IDs are visible in
                ``collection.schema``; the helper wraps option names in the
                double-quoted form Notion requires for automation values.
            source_refs: Optional ``{target_prop_id: (source_prop_id, source_prop_name)}``
                mapping that copies the trigger-row value of ``source_prop_id``
                into ``target_prop_id``. Works for text and email properties
                (Notion renders the mention as "페이지 실행의 {source_prop_name}").
            formula_refs: Optional ``{target_prop_id: (source_coll_id, source_prop_id, source_prop_name)}``
                for People-typed (or similarly typed) target properties. Uses
                the formula-style ``페이지 실행 · <prop>`` construct captured
                via UI's "사용자 지정 수식 작성" flow. Source collection id
                must be passed because People refs carry a collection pointer.
            trigger_page_refs: Optional list of target property IDs (usually
                Relation) that should be filled with the trigger page itself.
                Used when target DB has a Relation to source DB (the created
                page will link back to the triggering row).
            name: Optional automation display name.
            trigger: ``"pages_added"`` (default) or ``"page_props_any"`` (any
                property edit), or ``"page_props_filtered"`` combined with
                ``prop_filters`` for value-based gating.
            prop_filters: Used with ``trigger="page_props_filtered"``. List of
                ``{"property": <prop_id>, "filter": {"operator": <op>, "value": [...]}}``
                filters — e.g., ``{"property": "hcOM", "filter": {"operator": "enum_is",
                "value": [{"type": "exact", "value": "사용중"}]}}`` fires only when
                Select field ``hcOM`` becomes ``사용중``.

        Returns: New automation UUID on success, else None.
        """
        # @MX:NOTE: Payload captured 2026-04-21 via automate_add_page_capture.py
        # (action type "create_page", config.target.collection pointer +
        # config.values.title with simple text).
        source_coll = self._resolve_collection_id(source_database_id)
        target_coll = self._resolve_collection_id(target_database_id)
        automation_id = str(uuid.uuid4())
        action_id = str(uuid.uuid4())
        trigger_uuid = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)

        source_ptr = {
            "id": source_coll,
            "table": "collection",
            "spaceId": self.space_id,
        }
        target_ptr = {
            "table": "collection",
            "id": target_coll,
            "spaceId": self.space_id,
        }
        event: dict[str, Any] = {
            "pagesAdded": trigger == "pages_added",
            "pagePropertiesEdited": (
                {"type": "any"} if trigger == "page_props_any"
                else {"type": "none"}
            ),
            "source": {"pointer": source_ptr, "type": "collection"},
        }
        properties = {"name": name} if name else {}

        property_order: list[str] = ["title"]
        values_map: dict[str, Any] = {
            "title": {
                "action": "replace",
                "value": {"type": "simple", "value": [[title_text]]},
            }
        }
        for pid, option_name in (selects or {}).items():
            # @MX:NOTE: Notion's automation values for Select props wrap the
            # option name in double quotes (captured via UI: hcOM -> \"신청중\").
            property_order.append(pid)
            values_map[pid] = {
                "action": "replace",
                "value": {
                    "type": "simple",
                    "value": [[f'"{option_name}"']],
                },
            }
        for pid, (src_pid, src_name) in (source_refs or {}).items():
            # @MX:NOTE: Text/email source-row refs use the "fpp" formula
            # annotation. Captured shape 2026-04-21 from UI drive of
            # 소속/계정 이메일 mentions to "페이지 실행의 <prop>".
            property_order.append(pid)
            values_map[pid] = {
                "action": "replace",
                "value": {
                    "type": "simple",
                    "value": [
                        [
                            "‣",  # ‣
                            [
                                [
                                    "fpp",
                                    {
                                        "contextValueId": '{"global":"button_page","source":"global"}',
                                        "name": f"페이지 실행의 {src_name}",
                                        "property": src_pid,
                                        "valueSnapshot": "current",
                                    },
                                ]
                            ],
                        ],
                        [" "],
                    ],
                },
            }
        for pid, (src_coll, src_pid, src_name) in (formula_refs or {}).items():
            # @MX:NOTE: People/typed-ref source refs use the "formula" shape
            # with fv + "." + fpp(collection). Captured 2026-04-21 via UI
            # "사용자 지정 수식 작성" → 페이지 실행 · 대상자.
            property_order.append(pid)
            values_map[pid] = {
                "action": "replace",
                "value": {
                    "type": "formula",
                    "value": [
                        ["‣", [["fv", {"id": '{"global":"button_page","source":"global"}'}]]],
                        ["."],
                        ["‣", [["fpp", {
                            "collection": {
                                "table": "collection",
                                "id": src_coll,
                                "spaceId": self.space_id,
                            },
                            "property": src_pid,
                            "name": src_name,
                        }]]],
                    ],
                },
            }
        for pid in (trigger_page_refs or []):
            # Fill target Relation/People with the trigger page itself
            # ("페이지 실행" formula - just fv without dot/fpp).
            property_order.append(pid)
            values_map[pid] = {
                "action": "replace",
                "value": {
                    "type": "formula",
                    "value": [
                        ["‣", [["fv", {"id": '{"global":"button_page","source":"global"}'}]]],
                    ],
                },
            }
        action_config: dict[str, Any] = {
            "target": {"collection": target_ptr, "type": "collection"},
            "collection": target_ptr,
            "properties": property_order,
            "values": values_map,
        }

        ops: list[dict[str, Any]] = [
            {
                "pointer": source_ptr,
                "path": ["format", "automation_ids"],
                "command": "listAfter",
                "args": {"id": automation_id},
            },
            {
                "pointer": {
                    "table": "automation_action",
                    "id": action_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "set",
                "args": {
                    "id": action_id,
                    "type": "create_page",
                    "parent_id": automation_id,
                    "parent_table": "automation",
                    "alive": True,
                    "space_id": self.space_id,
                    "config": action_config,
                    "blocks": [],
                },
            },
            {
                "pointer": {
                    "id": automation_id,
                    "table": "automation",
                    "spaceId": self.space_id,
                },
                "path": ["action_ids"],
                "command": "listAfter",
                "args": {"id": action_id},
            },
            {
                "pointer": {
                    "table": "automation",
                    "id": automation_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "set",
                "args": {
                    "action_ids": [action_id],
                    "alive": True,
                    "id": automation_id,
                    "parent_id": source_coll,
                    "parent_table": "collection",
                    "properties": properties,
                    "space_id": self.space_id,
                    "status": "active",
                    "trigger": {
                        "id": trigger_uuid,
                        "type": "event",
                        "event": event,
                    },
                },
            },
            {
                "pointer": source_ptr,
                "path": [],
                "command": "update",
                "args": {
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            },
            {
                "pointer": {
                    "table": "automation",
                    "id": automation_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "created_by_id": self.user_id,
                    "created_by_table": "notion_user",
                    "created_time": now_ms,
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            },
        ]
        if source_database_id != source_coll:
            ops.append({
                "pointer": {
                    "table": "block",
                    "id": source_database_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            })
        result = self.save_transactions_fanout(
            ops, user_action="sdk.createAddPageAutomation",
        )
        return automation_id if result is not None else None

    def deactivate_database_automation(
        self,
        database_id: str,
        automation_id: str,
    ) -> bool:
        """Deactivate (soft-delete) an existing DB automation.

        Removes ``automation_id`` from ``collection.format.automation_ids`` and
        marks the automation + its actions ``alive=false``. Existing records
        are preserved; only the active binding is removed.

        Args:
            database_id: Source DB (block or collection id).
            automation_id: UUID of the automation to deactivate.

        Returns: True on success, False otherwise.
        """
        collection_id = self._resolve_collection_id(database_id)
        now_ms = int(time.time() * 1000)

        # Fetch the automation record to list its action_ids
        resp = self._post(
            "syncRecordValuesMain",
            {
                "requests": [{
                    "pointer": {
                        "id": automation_id,
                        "table": "automation",
                        "spaceId": self.space_id,
                    },
                    "version": -1,
                }]
            },
        ) or {}
        rm = resp.get("recordMap", {}) or {}
        entry = (rm.get("automation") or {}).get(automation_id) or {}
        val = (entry.get("value") or {}).get("value") or {}
        action_ids: list[str] = val.get("action_ids") or []

        ops: list[dict[str, Any]] = [
            {
                "pointer": {
                    "id": collection_id,
                    "table": "collection",
                    "spaceId": self.space_id,
                },
                "path": ["format", "automation_ids"],
                "command": "listRemove",
                "args": {"id": automation_id},
            },
            {
                "pointer": {
                    "id": automation_id,
                    "table": "automation",
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "alive": False,
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            },
            {
                "pointer": {
                    "id": collection_id,
                    "table": "collection",
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            },
        ]
        for aid in action_ids:
            ops.append({
                "pointer": {
                    "id": aid,
                    "table": "automation_action",
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {"alive": False},
            })
        if database_id != collection_id:
            ops.append({
                "pointer": {
                    "table": "block",
                    "id": database_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            })
        result = self.save_transactions_fanout(
            ops, user_action="sdk.deactivateDatabaseAutomation",
        )
        return result is not None

    # --- Guest invite (Share modal flow) ---

    def invite_guest_to_block(
        self,
        block_id: str,
        email: str,
        *,
        role: str = "editor",
    ) -> str | None:
        """Invite an external user as a guest to a block.

        Replicates the Share modal flow captured from Notion's web client:
          1. POST /createEmailUser → invitee user id
          2. POST /saveTransactionsFanout with three ops:
             - create invite record (``table=invite``)
             - setPermissionItem on the block (``permissions`` path)
             - update block last_edited metadata

        Args:
            block_id: Target block (page/database) UUID.
            email: Guest email to invite.
            role: Permission level — ``"editor"``, ``"reader"``, or
                ``"comment_only"``.

        Returns: The generated invite UUID on success, else ``None``.

        Known limitation: some Enterprise workspaces (e.g. ones that
        disallow self-serve signups) reject ``createEmailUser`` and
        ``findUser`` when called without the Share modal's UI warm-up
        chain (``getPageVisitors``, ``listAIConnectors``,
        ``getAllSpacePermissionGroupsWithMemberCount``, etc.) in the
        same session. If that happens, the server returns HTTP 400 with
        ``UserValidationError: Signup is not allowed``. In that case,
        fall back to the Playwright-driven Share modal flow or capture
        the Workspace Settings → Members → Invite guest path (which
        uses ``inviteGuestsToSpace``).
        """
        # @MX:NOTE: Payload captured from Share modal → "공유하기" flow.
        # The web client calls findUser + listUsers before createEmailUser;
        # the server rejects bare createEmailUser with "Signup is not allowed"
        # unless those lookups happened first in the same session.
        existing = self._post("findUser", {"email": email}) or {}
        invitee_id = (
            existing.get("user_id")
            or existing.get("userId")
            or existing.get("id")
        )
        if not invitee_id:
            rm = existing.get("recordMap") or {}
            users = rm.get("notion_user") or {}
            if users:
                invitee_id = next(iter(users.keys()))

        if not invitee_id:
            self._post(
                "listUsers",
                {
                    "limit": 10,
                    "query": email,
                    "spaceId": self.space_id,
                    "includeAliasSearch": True,
                },
            )
            # Re-check via findUser after listUsers primed server state.
            existing = self._post("findUser", {"email": email}) or {}
            invitee_id = (
                existing.get("user_id")
                or existing.get("userId")
                or existing.get("id")
            )
            if not invitee_id:
                rm = existing.get("recordMap") or {}
                users = rm.get("notion_user") or {}
                if users:
                    invitee_id = next(iter(users.keys()))

        if not invitee_id:
            user_resp = self._post(
                "createEmailUser",
                {
                    "email": email,
                    "preferredLocaleOrigin": "inferred_from_inviter",
                    "preferredLocale": "en-US",
                },
            ) or {}
            invitee_id = (
                user_resp.get("user_id")
                or user_resp.get("userId")
                or user_resp.get("id")
            )
            if not invitee_id:
                rm = user_resp.get("recordMap") or {}
                users = rm.get("notion_user") or {}
                if users:
                    invitee_id = next(iter(users.keys()))
        if not invitee_id:
            return None

        invite_id = str(uuid.uuid4())
        flow_id = str(uuid.uuid4())
        now_ms = int(time.time() * 1000)

        permission = {
            "type": "user_permission",
            "role": role,
            "user_id": invitee_id,
            "invite_id": invite_id,
        }
        block_ptr = {
            "id": block_id,
            "table": "block",
            "spaceId": self.space_id,
        }
        ops: list[dict[str, Any]] = [
            {
                "pointer": {
                    "table": "invite",
                    "id": invite_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "id": invite_id,
                    "version": 1,
                    "flow_id": flow_id,
                    "space_id": self.space_id,
                    "target_id": block_id,
                    "target_table": "block",
                    "inviter_id": self.user_id,
                    "inviter_table": "notion_user",
                    "invitee_id": invitee_id,
                    "invitee_table_or_group": "notion_user",
                    "message": "",
                    "created_time": now_ms,
                    "attributes": {
                        "permission": permission,
                        "origin_type": "share_menu",
                    },
                },
            },
            {
                "pointer": block_ptr,
                "path": ["permissions"],
                "command": "setPermissionItem",
                "args": permission,
            },
            {
                "pointer": block_ptr,
                "path": [],
                "command": "update",
                "args": {
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            },
        ]
        result = self.save_transactions_fanout(
            ops, user_action="permissionsActions.savePermissionItems"
        )
        return invite_id if result is not None else None

    def delete_database_automation(self, automation_id: str) -> bool:
        """Soft-delete a database automation (sets ``alive: false``)."""
        now_ms = int(time.time() * 1000)
        ops: list[dict[str, Any]] = [
            {
                "pointer": {
                    "table": "automation",
                    "id": automation_id,
                    "spaceId": self.space_id,
                },
                "path": [],
                "command": "update",
                "args": {
                    "alive": False,
                    "last_edited_time": now_ms,
                    "last_edited_by_id": self.user_id,
                    "last_edited_by_table": "notion_user",
                },
            }
        ]
        result = self.save_transactions_fanout(
            ops, user_action="sdk.deleteDatabaseAutomation",
        )
        return result is not None

    # --- Authentication ---

    @classmethod
    def login(
        cls,
        email: str,
        password: str,
        space_id: str | None = None,
        headed: bool = True,
        slow_mo: int = 100,
    ) -> dict[str, str]:
        """Log in to Notion via browser and return credentials.

        Uses Playwright to automate the login flow with hCaptcha auto-pass.
        Requires headed=True (default) for hCaptcha to resolve.

        Args:
            email: Notion account email.
            password: Account password.
            space_id: Workspace space ID (extracted from response if not given).
            headed: Show browser window. Must be True for hCaptcha.
            slow_mo: Delay between actions in ms (human-like typing).

        Returns:
            Dict with 'token_v2', 'user_id', and 'space_id'.

        Raises:
            RuntimeError: If login fails or token_v2 is not received.
        """
        import random as _random

        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "playwright is required for login. Install with: pip install playwright && playwright install chromium"
            ) from exc

        login_result: dict[str, str] = {}

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=not headed,
                channel="chrome",
                args=["--window-position=3000,3000", "--window-size=1440,900"],
            )
            ctx = browser.new_context(
                viewport={"width": 1440, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()

            # Capture loginWithEmail response for user_id
            def _on_resp(resp: object) -> None:
                url = getattr(resp, "url", "")
                if "loginWithEmail" in url:
                    try:
                        body = resp.json()  # type: ignore[union-attr]
                        if isinstance(body, dict) and "userId" in body:
                            login_result["user_id"] = body["userId"]
                    except Exception:
                        pass

            page.on("response", _on_resp)

            logger.info("Opening Notion login page...")
            page.goto("https://www.notion.so/login", wait_until="domcontentloaded", timeout=30000)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            time.sleep(4)

            # Email
            logger.info("Entering email...")
            email_input = page.locator('input[type="email"]').first
            email_input.click()
            time.sleep(0.5)
            for ch in email:
                page.keyboard.type(ch)
                time.sleep(_random.uniform(0.05, 0.12))
            time.sleep(2)

            # Click continue
            for label in ["계속", "Continue", "이메일로 계속"]:
                btn = page.get_by_role("button", name=label)
                if btn.first.is_visible(timeout=2000):
                    btn.first.click()
                    break
            time.sleep(8)

            # Password
            logger.info("Entering password...")
            pw_input = page.locator('input[type="password"]').first
            if not pw_input.is_visible(timeout=5000):
                ctx.close()
                browser.close()
                raise RuntimeError(
                    "Password field not found. Notion may require email verification "
                    "(mustReverify). Try again or use a slower connection."
                )

            pw_input.click()
            time.sleep(0.5)
            for ch in password:
                page.keyboard.type(ch)
                time.sleep(_random.uniform(0.06, 0.15))
            time.sleep(2)

            # Click login
            logger.info("Submitting login...")
            for label in ["비밀번호로 계속하기", "Continue with password", "Continue", "Log in"]:
                btn = page.get_by_role("button", name=label)
                if btn.first.is_visible(timeout=2000):
                    btn.first.click()
                    break
            else:
                page.keyboard.press("Enter")

            # Wait for redirect
            for _ in range(30):
                time.sleep(1)
                token = next(
                    (c for c in ctx.cookies() if c["name"] == "token_v2"), None
                )
                if token:
                    login_result["token_v2"] = token["value"]
                    break
                if "login" not in page.url.lower():
                    # Check cookies after redirect
                    token = next(
                        (c for c in ctx.cookies() if c["name"] == "token_v2"), None
                    )
                    if token:
                        login_result["token_v2"] = token["value"]
                    break

            ctx.close()
            browser.close()

        if "token_v2" not in login_result:
            raise RuntimeError(
                "Login failed: token_v2 not received. "
                "Check credentials or try with headed=True."
            )

        if space_id:
            login_result["space_id"] = space_id

        return login_result
