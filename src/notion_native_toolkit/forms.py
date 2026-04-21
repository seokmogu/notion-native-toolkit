"""Notion internal API wrappers for Form view management.

Notion's public API v1 does not expose Form views, questions, layouts, or
Automations. This module wraps Notion's undocumented `api/v3` endpoints
(`saveTransactionsMain`, `saveTransactionsFanout`, `syncRecordValues`) to
manipulate Form-related records programmatically.

All functions require a logged-in Playwright Page object (for session
cookies) and an explicit NotionInternalContext with `space_id` and `user_id`.

The captured API patterns were reverse-engineered by observing Notion's
web client network traffic during UI interactions such as "Add view → Form",
"Add question", "Edit form title", and layout reordering.
"""

from __future__ import annotations

import json
import random
import string
import time
import uuid
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Page

INTERNAL_API = "https://www.notion.so/api/v3"
DEFAULT_CLIENT_VERSION = "23.13.20260411.0653"


@dataclass(frozen=True)
class NotionInternalContext:
    """Authentication context for Notion internal API calls.

    Attributes:
        space_id: Notion workspace UUID.
        user_id: Active Notion user UUID.
        client_version: Value for the `notion-client-version` header.
    """

    space_id: str
    user_id: str
    client_version: str = DEFAULT_CLIENT_VERSION

    def headers(self, referer: str) -> dict[str, str]:
        """Return the standard header set for api/v3 requests."""
        return {
            "content-type": "application/json",
            "x-notion-space-id": self.space_id,
            "x-notion-active-user-header": self.user_id,
            "notion-client-version": self.client_version,
            "referer": referer,
        }


def _random_module_id(length: int = 4) -> str:
    """Generate a nanoid-style ID for form_layout_schema module entries."""
    chars = string.ascii_letters + string.digits + "_-^"
    return "".join(random.choices(chars, k=length))


def _now_ms() -> int:
    """Return the current timestamp in milliseconds."""
    return int(time.time() * 1000)


async def _post(
    page: Page,
    *,
    path: str,
    body: dict[str, Any],
    ctx: NotionInternalContext,
    referer: str,
) -> dict[str, Any]:
    """POST to a Notion internal api/v3 endpoint and return the parsed body."""
    resp = await page.request.post(
        f"{INTERNAL_API}/{path}",
        data=json.dumps(body),
        headers=ctx.headers(referer),
    )
    if resp.status != 200:
        text = await resp.text()
        raise RuntimeError(f"api/v3/{path} failed: HTTP {resp.status}: {text[:500]}")
    return await resp.json()


async def create_form_view(
    page: Page,
    *,
    db_block_id: str,
    collection_id: str,
    ctx: NotionInternalContext,
    referer: str,
    view_name: str = "양식 작성기",
) -> dict[str, str]:
    """Create a new Form view on a Notion database.

    Args:
        page: Logged-in Playwright Page.
        db_block_id: Block UUID of the database.
        collection_id: Collection UUID (different from block ID).
        ctx: Auth context.
        referer: URL of the database page (used as HTTP referer).
        view_name: Name shown on the view tab.

    Returns:
        Dict with keys ``view_id``, ``form_block_id``, ``layout_id``,
        ``first_question_id``.
    """
    form_block_id = str(uuid.uuid4())
    layout_id = str(uuid.uuid4())
    first_question_id = str(uuid.uuid4())
    view_id = str(uuid.uuid4())
    ts = _now_ms()

    form_block_op: dict[str, Any] = {
        "pointer": {"table": "block", "id": form_block_id, "spaceId": ctx.space_id},
        "path": [],
        "command": "set",
        "args": {
            "id": form_block_id,
            "type": "form",
            "parent_id": view_id,
            "parent_table": "collection_view",
            "alive": True,
            "permissions": [
                {
                    "type": "space_permission",
                    "role": "reader",
                    "unlisted_timestamp": ts,
                }
            ],
            "properties": {"title": []},
            "space_id": ctx.space_id,
            "created_time": ts,
            "created_by_table": "notion_user",
            "created_by_id": ctx.user_id,
            "last_edited_time": ts,
            "last_edited_by_id": ctx.user_id,
            "last_edited_by_table": "notion_user",
        },
    }

    layout_op: dict[str, Any] = {
        "pointer": {"table": "layout", "id": layout_id, "spaceId": ctx.space_id},
        "path": [],
        "command": "set",
        "args": {
            "space_id": ctx.space_id,
            "parent_table": "block",
            "parent_id": form_block_id,
            "created_time": ts,
            "created_by_id": ctx.user_id,
            "created_by_table": "notion_user",
            "last_edited_time": ts,
            "last_edited_by_id": ctx.user_id,
            "last_edited_by_table": "notion_user",
            "modules": {
                "form_layout_schema": [
                    {"id": _random_module_id(), "type": "cover"},
                    {"id": _random_module_id(), "type": "formTitle"},
                    {
                        "id": _random_module_id(),
                        "type": "formQuestion",
                        "formQuestionId": first_question_id,
                    },
                    {"id": _random_module_id(), "type": "formSubmit"},
                ]
            },
            "id": layout_id,
        },
    }

    link_layout_op: dict[str, Any] = {
        "pointer": {"table": "block", "id": form_block_id, "spaceId": ctx.space_id},
        "path": ["format"],
        "command": "update",
        "args": {
            "form_layout_pointer": {
                "id": layout_id,
                "spaceId": ctx.space_id,
                "table": "layout",
            }
        },
    }

    first_question_op: dict[str, Any] = {
        "pointer": {
            "table": "form_question",
            "id": first_question_id,
            "spaceId": ctx.space_id,
        },
        "path": [],
        "command": "set",
        "args": {
            "id": first_question_id,
            "version": 1,
            "space_id": ctx.space_id,
            "parent_table": "layout",
            "parent_id": layout_id,
            "alive": True,
            "config": {
                "propertyId": "title",
                "name": [],
                "shouldSyncQuestionNameToPropertyName": True,
            },
        },
    }

    view_op: dict[str, Any] = {
        "pointer": {
            "table": "collection_view",
            "id": view_id,
            "spaceId": ctx.space_id,
        },
        "path": [],
        "command": "set",
        "args": {
            "type": "form_editor",
            "parent_id": db_block_id,
            "parent_table": "block",
            "alive": True,
            "space_id": ctx.space_id,
            "name": view_name,
            "format": {
                "form_block_pointer": {
                    "id": form_block_id,
                    "spaceId": ctx.space_id,
                    "table": "block",
                },
                "collection_pointer": {
                    "id": collection_id,
                    "spaceId": ctx.space_id,
                    "table": "collection",
                },
            },
            "id": view_id,
        },
    }

    register_view_op: dict[str, Any] = {
        "pointer": {"id": db_block_id, "table": "block", "spaceId": ctx.space_id},
        "path": ["view_ids"],
        "command": "listAfter",
        "args": {"id": view_id},
    }

    payload: dict[str, Any] = {
        "requestId": str(uuid.uuid4()),
        "transactions": [
            {
                "id": str(uuid.uuid4()),
                "spaceId": ctx.space_id,
                "debug": {
                    "userAction": "CollectionViewTabBar.createGenericViewType"
                },
                "operations": [
                    form_block_op,
                    layout_op,
                    link_layout_op,
                    first_question_op,
                    view_op,
                    register_view_op,
                ],
            }
        ],
        "unretryable_error_behavior": "continue",
    }

    await _post(
        page,
        path="saveTransactionsMain",
        body=payload,
        ctx=ctx,
        referer=referer,
    )

    return {
        "view_id": view_id,
        "form_block_id": form_block_id,
        "layout_id": layout_id,
        "first_question_id": first_question_id,
    }


async def add_form_question(
    page: Page,
    *,
    layout_id: str,
    property_id: str,
    name: str,
    ctx: NotionInternalContext,
    referer: str,
) -> dict[str, str]:
    """Append a new question to an existing form layout.

    The question is appended to the tail of ``form_layout_schema``. Callers
    that want the submit button to remain last should follow up with
    :func:`reorder_form_layout` once all questions have been added.

    Args:
        page: Logged-in Playwright Page.
        layout_id: Layout record UUID.
        property_id: Database property ID the question maps to.
        name: Display label for the question.
        ctx: Auth context.
        referer: URL of the database page.

    Returns:
        Dict with keys ``form_question_id`` and ``module_id``.
    """
    form_question_id = str(uuid.uuid4())
    module_id = _random_module_id()
    ts = _now_ms()

    create_question_op: dict[str, Any] = {
        "pointer": {
            "table": "form_question",
            "id": form_question_id,
            "spaceId": ctx.space_id,
        },
        "path": [],
        "command": "set",
        "args": {
            "id": form_question_id,
            "version": 1,
            "space_id": ctx.space_id,
            "parent_table": "layout",
            "parent_id": layout_id,
            "alive": True,
            "config": {
                "propertyId": property_id,
                "name": [[name]],
                "shouldSyncQuestionNameToPropertyName": False,
            },
        },
    }

    append_layout_op: dict[str, Any] = {
        "command": "keyedObjectListUpdate",
        "pointer": {"id": layout_id, "table": "layout", "spaceId": ctx.space_id},
        "path": ["modules", "form_layout_schema"],
        "args": {
            "value": {
                "type": "formQuestion",
                "id": module_id,
                "formQuestionId": form_question_id,
            }
        },
    }

    touch_layout_op: dict[str, Any] = {
        "pointer": {"id": layout_id, "table": "layout", "spaceId": ctx.space_id},
        "path": [],
        "command": "update",
        "args": {
            "last_edited_time": ts,
            "last_edited_by_id": ctx.user_id,
            "last_edited_by_table": "notion_user",
        },
    }

    payload: dict[str, Any] = {
        "requestId": str(uuid.uuid4()),
        "transactions": [
            {
                "id": str(uuid.uuid4()),
                "spaceId": ctx.space_id,
                "debug": {
                    "userAction": "FormQuestionCreateSettings.createFormQuestion"
                },
                "operations": [create_question_op, append_layout_op, touch_layout_op],
            }
        ],
        "unretryable_error_behavior": "continue",
    }

    await _post(
        page,
        path="saveTransactionsFanout",
        body=payload,
        ctx=ctx,
        referer=referer,
    )

    return {"form_question_id": form_question_id, "module_id": module_id}


async def set_form_title(
    page: Page,
    *,
    form_block_id: str,
    title: str,
    ctx: NotionInternalContext,
    referer: str,
) -> None:
    """Set the title of a Form block (the large heading above questions).

    Args:
        page: Logged-in Playwright Page.
        form_block_id: Form block UUID.
        title: New title text.
        ctx: Auth context.
        referer: URL of the form view.
    """
    ts = _now_ms()

    set_title_op: dict[str, Any] = {
        "pointer": {"table": "block", "id": form_block_id, "spaceId": ctx.space_id},
        "path": ["properties", "title"],
        "command": "set",
        "args": [[title]],
    }

    touch_op: dict[str, Any] = {
        "pointer": {"table": "block", "id": form_block_id, "spaceId": ctx.space_id},
        "path": [],
        "command": "update",
        "args": {
            "last_edited_time": ts,
            "last_edited_by_id": ctx.user_id,
            "last_edited_by_table": "notion_user",
        },
    }

    payload: dict[str, Any] = {
        "requestId": str(uuid.uuid4()),
        "transactions": [
            {
                "id": str(uuid.uuid4()),
                "spaceId": ctx.space_id,
                "debug": {"userAction": "CollectionFormTitle.onChange"},
                "operations": [set_title_op, touch_op],
            }
        ],
        "unretryable_error_behavior": "continue",
    }

    await _post(
        page,
        path="saveTransactionsFanout",
        body=payload,
        ctx=ctx,
        referer=referer,
    )


async def reorder_form_layout(
    page: Page,
    *,
    layout_id: str,
    new_modules: list[dict[str, Any]],
    ctx: NotionInternalContext,
    referer: str,
) -> None:
    """Replace ``form_layout_schema`` with a new ordered list of modules.

    Typically used to move ``formSubmit`` back to the tail after new
    questions have been appended via :func:`add_form_question`.

    Args:
        page: Logged-in Playwright Page.
        layout_id: Layout record UUID.
        new_modules: Ordered list of module dicts. Each dict has at minimum
            ``id`` and ``type`` keys. ``formQuestion`` modules also carry
            ``formQuestionId``.
        ctx: Auth context.
        referer: URL of the form view.
    """
    ts = _now_ms()

    set_layout_op: dict[str, Any] = {
        "pointer": {"table": "layout", "id": layout_id, "spaceId": ctx.space_id},
        "path": ["modules", "form_layout_schema"],
        "command": "set",
        "args": new_modules,
    }

    touch_op: dict[str, Any] = {
        "pointer": {"table": "layout", "id": layout_id, "spaceId": ctx.space_id},
        "path": [],
        "command": "update",
        "args": {
            "last_edited_time": ts,
            "last_edited_by_id": ctx.user_id,
            "last_edited_by_table": "notion_user",
        },
    }

    payload: dict[str, Any] = {
        "requestId": str(uuid.uuid4()),
        "transactions": [
            {
                "id": str(uuid.uuid4()),
                "spaceId": ctx.space_id,
                "debug": {"userAction": "FormLayout.repair"},
                "operations": [set_layout_op, touch_op],
            }
        ],
        "unretryable_error_behavior": "continue",
    }

    await _post(
        page,
        path="saveTransactionsFanout",
        body=payload,
        ctx=ctx,
        referer=referer,
    )


async def delete_form_question(
    page: Page,
    *,
    form_question_id: str,
    ctx: NotionInternalContext,
    referer: str,
) -> None:
    """Soft-delete a form_question record by marking ``alive`` as False.

    This only removes the question record. Callers must also remove the
    corresponding entry from ``form_layout_schema`` via
    :func:`reorder_form_layout` to hide the question from the form UI.

    Args:
        page: Logged-in Playwright Page.
        form_question_id: Question UUID to mark inactive.
        ctx: Auth context.
        referer: URL of the form view.
    """
    ts = _now_ms()

    delete_op: dict[str, Any] = {
        "pointer": {
            "table": "form_question",
            "id": form_question_id,
            "spaceId": ctx.space_id,
        },
        "path": [],
        "command": "update",
        "args": {
            "alive": False,
            "last_edited_time": ts,
            "last_edited_by_id": ctx.user_id,
            "last_edited_by_table": "notion_user",
        },
    }

    payload: dict[str, Any] = {
        "requestId": str(uuid.uuid4()),
        "transactions": [
            {
                "id": str(uuid.uuid4()),
                "spaceId": ctx.space_id,
                "debug": {"userAction": "FormQuestion.delete"},
                "operations": [delete_op],
            }
        ],
        "unretryable_error_behavior": "continue",
    }

    await _post(
        page,
        path="saveTransactionsFanout",
        body=payload,
        ctx=ctx,
        referer=referer,
    )


async def get_form_layout(
    page: Page,
    *,
    layout_id: str,
    ctx: NotionInternalContext,
    referer: str,
) -> dict[str, Any]:
    """Fetch a layout record and return the inner value dict.

    The returned dict has ``modules.form_layout_schema`` containing the
    ordered list of form modules, plus standard metadata such as
    ``parent_id`` and ``last_edited_time``.

    Args:
        page: Logged-in Playwright Page.
        layout_id: Layout record UUID.
        ctx: Auth context.
        referer: URL of the form view.

    Returns:
        The layout value dict. Empty dict if the record is missing.
    """
    payload: dict[str, Any] = {
        "requests": [
            {
                "pointer": {
                    "table": "layout",
                    "id": layout_id,
                    "spaceId": ctx.space_id,
                },
                "version": -1,
            }
        ]
    }
    data = await _post(
        page,
        path="syncRecordValues",
        body=payload,
        ctx=ctx,
        referer=referer,
    )
    record: dict[str, Any] = (
        data.get("recordMap", {})
        .get("layout", {})
        .get(layout_id, {})
        .get("value", {})
        .get("value", {})
    )
    return record


__all__ = [
    "NotionInternalContext",
    "create_form_view",
    "add_form_question",
    "set_form_title",
    "reorder_form_layout",
    "delete_form_question",
    "get_form_layout",
]
