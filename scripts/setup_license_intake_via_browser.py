"""Install the 7 Claude.ai license-intake automations via the live browser.

Runs all /api/v3/ calls (resolve collection id, saveTransactionsFanout) through
Playwright's ``page.evaluate`` so the browser's existing auth context is used.
Side-steps the cached cookies.json / internal client auth issue entirely.

Prerequisites:
- ``/tmp/pw/server.py`` running (CDP on :9222, logged into Notion)
- Run beforehand: ``python scripts/automate_add_page_capture.py`` (at least once)

Usage:
    uv run python scripts/setup_license_intake_via_browser.py
    uv run python scripts/setup_license_intake_via_browser.py --deactivate
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from typing import Any

from playwright.sync_api import sync_playwright

SPACE_ID = "7197d832-2b04-81a8-94d3-00038ba30695"
USER_ID = "2a8d872b-594c-812a-a61b-0002a4cd405c"

# Block IDs from docs/11-license-intake/README.md §11.5
APP_DB = "33f7d832-2b04-818e-8919-cf8760e8782c"
MGT_DB = "33f7d832-2b04-8118-8a2d-da3f70b00b62"
HIS_DB = "33f7d832-2b04-81b8-8548-fb144bd39c89"

# Collection IDs (resolved at runtime via resolve_collection_id)
# APP DB source properties:
APP_PROP_EMAIL = "=L~s"       # 계정 이메일 (email)
APP_PROP_SOSOK = "]aja"       # 소속 (text)
APP_PROP_REASON = "{>Dk"      # 신청 사유 (text)
APP_PROP_TARGET = "{dV<"      # 대상자 (person)
APP_PROP_PLAN = "_shS"        # 희망 플랜 (select)
# MGT DB target properties:
MGT_PROP_STATUS = "hcOM"      # 현재 상태 (select)
MGT_PROP_SOSOK = "mU@q"       # 소속 (text)
MGT_PROP_EMAIL = "_e:N"       # 계정 이메일 (email)
MGT_PROP_TARGET = "u|hV"      # 대상자 (person)
MGT_PROP_APP_REL = "Z_Ma"     # 신청 원본 (relation to APP)
MGT_PROP_PLAN = "R^Pt"        # 현재 플랜 (select)
MGT_PROP_APPROVER = "\\UzM"   # 승인자 (person)
# HIS DB target properties:
HIS_PROP_COMMENT = "GmE@"     # 코멘트 (text)
HIS_PROP_MGT_REL = "ZJTl"     # 대상자 (relation to MGT)
HIS_PROP_HANDLER = "~pdU"     # 처리자 (person)
HIS_EVENT_TYPE = None         # resolved at runtime

RULES = [
    {"id": "AUTO-1", "name": "AUTO-1 신청→관리",
     "source": APP_DB, "target": MGT_DB,
     "title": "신규 신청 접수", "trigger": "pages_added",
     "selects": {MGT_PROP_STATUS: "신청중"},
     "source_refs": {
         MGT_PROP_SOSOK: (APP_PROP_SOSOK, "소속"),
         MGT_PROP_EMAIL: (APP_PROP_EMAIL, "계정 이메일"),
     },
     # 대상자(person) + 현재 플랜(select) copied from source via formula-style
     # refs (collection pointer). Collection id resolved at runtime.
     "formula_refs_tpl": [
         (MGT_PROP_TARGET, "source", APP_PROP_TARGET, "대상자"),
         (MGT_PROP_PLAN, "source", APP_PROP_PLAN, "희망 플랜"),
     ],
     # MGT 신청 원본 → relation to APP row (= trigger page itself).
     "trigger_page_refs": [MGT_PROP_APP_REL],
     # MGT 승인자 ← APP row's Created by
     "page_creator_refs": [MGT_PROP_APPROVER]},
    {"id": "AUTO-2", "name": "AUTO-2 신청→이력 신청 이벤트",
     "source": APP_DB, "target": HIS_DB,
     "title": "신청 이벤트", "trigger": "pages_added",
     "selects": {"EVENT_TYPE": "신청"},
     "source_refs": {HIS_PROP_COMMENT: (APP_PROP_REASON, "신청 사유")},
     "page_creator_refs": [HIS_PROP_HANDLER]},
    # AUTO-3~7: trigger is MGT property edit with SPECIFIC value filter.
    # Distinguishes which automation fires based on 현재 상태 or 현재 플랜 value.
    {"id": "AUTO-3", "name": "AUTO-3 관리→이력 배정",
     "source": MGT_DB, "target": HIS_DB,
     "title": "배정 이벤트", "trigger": "page_props_filtered",
     "prop_filters": [{"property": MGT_PROP_STATUS, "filter": {"operator":"enum_is", "value":[{"type":"exact","value":"사용중"}]}}],
     "selects": {"EVENT_TYPE": "배정"},
     "trigger_page_refs": [HIS_PROP_MGT_REL]},
    {"id": "AUTO-4", "name": "AUTO-4 관리→이력 반려",
     "source": MGT_DB, "target": HIS_DB,
     "title": "반려 이벤트", "trigger": "page_props_filtered",
     "prop_filters": [{"property": MGT_PROP_STATUS, "filter": {"operator":"enum_is", "value":[{"type":"exact","value":"반려"}]}}],
     "selects": {"EVENT_TYPE": "반려"},
     "trigger_page_refs": [HIS_PROP_MGT_REL]},
    {"id": "AUTO-5", "name": "AUTO-5 관리→이력 중지",
     "source": MGT_DB, "target": HIS_DB,
     "title": "중지 이벤트", "trigger": "page_props_filtered",
     "prop_filters": [{"property": MGT_PROP_STATUS, "filter": {"operator":"enum_is", "value":[{"type":"exact","value":"중지"}]}}],
     "selects": {"EVENT_TYPE": "중지"},
     "trigger_page_refs": [HIS_PROP_MGT_REL]},
    # AUTO-6 재활성: 중지 → 사용중 전환 — same filter as AUTO-3 would fire on both
    # normal "배정" and "재활성" 상태=사용중 transitions. Without prior-value
    # conditioning (Notion doesn't expose that via our payload shape), we let
    # AUTO-3 cover both cases and drop AUTO-6. Left here for documentation.
    # {"id": "AUTO-6", ...}   # merged into AUTO-3
    {"id": "AUTO-7", "name": "AUTO-7 관리→이력 플랜변경",
     "source": MGT_DB, "target": HIS_DB,
     "title": "플랜변경 이벤트", "trigger": "page_props_filtered",
     # Fires on ANY 현재 플랜 edit (to any of the 3 plan values).
     "prop_filters": [{"property": "R^Pt", "filter": {"operator":"enum_is", "value":[
         {"type":"exact","value":"Team Standard"},
         {"type":"exact","value":"Team Premium"},
         {"type":"exact","value":"Max 20x"},
     ]}}],
     "selects": {"EVENT_TYPE": "플랜변경"},
     "trigger_page_refs": [HIS_PROP_MGT_REL]},
]


def resolve_his_event_type_prop_id(page) -> str:
    """Look up HIS DB schema and find the property id for `이벤트 유형`."""
    cid = resolve_collection_id(page, HIS_DB)
    resp = fetch_via(page, "syncRecordValuesMain", {
        "requests": [{"pointer": {"id": cid, "table": "collection", "spaceId": SPACE_ID}, "version": -1}]
    })
    schema = (resp.get("recordMap", {}).get("collection") or {}).get(cid, {})
    schema = (schema.get("value") or {}).get("value", {}).get("schema", {})
    for pid, spec in schema.items():
        if spec.get("name") == "이벤트 유형":
            return pid
    raise RuntimeError("이벤트 유형 not found in HIS schema")


JS_FETCH = """
async ({path, body}) => {
    const r = await fetch('/api/v3/' + path, {
        method: 'POST', credentials: 'include',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body),
    });
    const text = await r.text();
    let parsed = null;
    try { parsed = JSON.parse(text); } catch { parsed = text; }
    return {status: r.status, body: parsed};
}
"""


def fetch_via(page, path: str, body: dict[str, Any]) -> dict[str, Any]:
    res = page.evaluate(JS_FETCH, {"path": path, "body": body})
    if res["status"] != 200:
        raise RuntimeError(f"{path} failed: HTTP {res['status']}: {str(res['body'])[:300]}")
    return res["body"]


def resolve_collection_id(page, db_block_id: str) -> str:
    resp = fetch_via(page, "syncRecordValuesMain", {
        "requests": [{"pointer": {"id": db_block_id, "table": "block", "spaceId": SPACE_ID}, "version": -1}]
    })
    block = (resp.get("recordMap", {}).get("block") or {}).get(db_block_id) or {}
    val = (block.get("value") or {}).get("value") or {}
    cid = val.get("collection_id") or ((val.get("format") or {}).get("collection_pointer") or {}).get("id")
    if not cid:
        raise RuntimeError(f"cannot resolve collection_id for {db_block_id}")
    return cid


def build_create_ops(
    source_coll: str,
    source_block: str,
    target_coll: str,
    title_text: str,
    name: str,
    trigger: str,
    selects: dict[str, str] | None = None,
    source_refs: dict[str, tuple] | None = None,
    formula_refs: dict[str, tuple] | None = None,
    trigger_page_refs: list[str] | None = None,
    page_creator_refs: list[str] | None = None,
    prop_filters: list[dict] | None = None,
) -> tuple:
    auto_id = str(uuid.uuid4())
    action_id = str(uuid.uuid4())
    trigger_uuid = str(uuid.uuid4())
    now = int(time.time() * 1000)

    source_ptr = {"id": source_coll, "table": "collection", "spaceId": SPACE_ID}
    target_ptr = {"table": "collection", "id": target_coll, "spaceId": SPACE_ID}
    if trigger == "page_props_filtered":
        pp_edited = {"type": "all", "all": prop_filters or []}
    elif trigger == "page_props_any":
        pp_edited = {"type": "any"}
    else:
        pp_edited = {"type": "none"}
    event = {
        "pagesAdded": trigger == "pages_added",
        "pagePropertiesEdited": pp_edited,
        "source": {"pointer": source_ptr, "type": "collection"},
    }
    property_order: list[str] = ["title"]
    values_map: dict[str, Any] = {
        "title": {"action": "replace", "value": {"type": "simple", "value": [[title_text]]}}
    }
    for pid, opt in (selects or {}).items():
        property_order.append(pid)
        values_map[pid] = {
            "action": "replace",
            "value": {"type": "simple", "value": [[f'"{opt}"']]},
        }
    for pid, (src_pid, src_name) in (source_refs or {}).items():
        property_order.append(pid)
        values_map[pid] = {
            "action": "replace",
            "value": {
                "type": "simple",
                "value": [
                    [
                        "‣",
                        [[
                            "fpp",
                            {
                                "contextValueId": '{"global":"button_page","source":"global"}',
                                "name": f"페이지 실행의 {src_name}",
                                "property": src_pid,
                                "valueSnapshot": "current",
                            },
                        ]],
                    ],
                    [" "],
                ],
            },
        }
    for pid, (src_coll, src_pid, src_name) in (formula_refs or {}).items():
        property_order.append(pid)
        values_map[pid] = {
            "action": "replace",
            "value": {
                "type": "formula",
                "value": [
                    ["‣", [["fv", {"id": '{"global":"button_page","source":"global"}'}]]],
                    ["."],
                    ["‣", [["fpp", {
                        "collection": {"table":"collection", "id": src_coll, "spaceId": SPACE_ID},
                        "property": src_pid,
                        "name": src_name,
                    }]]],
                ],
            },
        }
    for pid in (trigger_page_refs or []):
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
    for pid in (page_creator_refs or []):
        property_order.append(pid)
        values_map[pid] = {
            "action": "replace",
            "value": {
                "type": "simple",
                "value": [
                    ["["],
                    ["‣", [["fv", {"id": '{"global":"page_creator","source":"global"}'}]]],
                    ["]"],
                ],
            },
        }
    ops = [
        {"pointer": source_ptr, "path": ["format", "automation_ids"],
         "command": "listAfter", "args": {"id": auto_id}},
        {"pointer": {"table": "automation_action", "id": action_id, "spaceId": SPACE_ID},
         "path": [], "command": "set",
         "args": {
            "id": action_id, "type": "create_page",
            "parent_id": auto_id, "parent_table": "automation",
            "alive": True, "space_id": SPACE_ID,
            "config": {
                "target": {"collection": target_ptr, "type": "collection"},
                "collection": target_ptr,
                "properties": property_order,
                "values": values_map,
            },
            "blocks": [],
        }},
        {"pointer": {"id": auto_id, "table": "automation", "spaceId": SPACE_ID},
         "path": ["action_ids"], "command": "listAfter", "args": {"id": action_id}},
        {"pointer": {"table": "automation", "id": auto_id, "spaceId": SPACE_ID},
         "path": [], "command": "set",
         "args": {
            "action_ids": [action_id], "alive": True, "id": auto_id,
            "parent_id": source_coll, "parent_table": "collection",
            "properties": {"name": name} if name else {},
            "space_id": SPACE_ID, "status": "active",
            "trigger": {"id": trigger_uuid, "type": "event", "event": event},
        }},
        {"pointer": source_ptr, "path": [], "command": "update",
         "args": {"last_edited_time": now, "last_edited_by_id": USER_ID, "last_edited_by_table": "notion_user"}},
        {"pointer": {"table": "automation", "id": auto_id, "spaceId": SPACE_ID},
         "path": [], "command": "update",
         "args": {"created_by_id": USER_ID, "created_by_table": "notion_user",
                  "created_time": now, "last_edited_time": now,
                  "last_edited_by_id": USER_ID, "last_edited_by_table": "notion_user"}},
        {"pointer": {"table": "block", "id": source_block, "spaceId": SPACE_ID},
         "path": [], "command": "update",
         "args": {"last_edited_time": now, "last_edited_by_id": USER_ID, "last_edited_by_table": "notion_user"}},
    ]
    return ops, auto_id, action_id


def save_transactions(page, ops: list[dict[str, Any]], user_action: str) -> None:
    body = {
        "requestId": str(uuid.uuid4()),
        "transactions": [{
            "id": str(uuid.uuid4()), "spaceId": SPACE_ID,
            "debug": {"userAction": user_action},
            "operations": ops,
        }],
        "unretryable_error_behavior": "continue",
    }
    fetch_via(page, "saveTransactionsFanout", body)


def list_automations(page, db_block_id: str) -> list[dict[str, Any]]:
    cid = resolve_collection_id(page, db_block_id)
    resp = fetch_via(page, "syncRecordValuesMain", {
        "requests": [{"pointer": {"id": cid, "table": "collection", "spaceId": SPACE_ID}, "version": -1}]
    })
    coll = (resp.get("recordMap", {}).get("collection") or {}).get(cid) or {}
    val = (coll.get("value") or {}).get("value") or {}
    auto_ids = (val.get("format") or {}).get("automation_ids") or []
    out = []
    for aid in auto_ids:
        r = fetch_via(page, "syncRecordValuesMain", {
            "requests": [{"pointer": {"id": aid, "table": "automation", "spaceId": SPACE_ID}, "version": -1}]
        })
        entry = (r.get("recordMap", {}).get("automation") or {}).get(aid) or {}
        v = (entry.get("value") or {}).get("value") or {}
        if v:
            out.append(v)
    return out


def deactivate_all(page) -> None:
    for db_block in (APP_DB, MGT_DB, HIS_DB):
        autos = list_automations(page, db_block)
        cid = resolve_collection_id(page, db_block)
        now = int(time.time() * 1000)
        for a in autos:
            aid = a["id"]
            action_ids = a.get("action_ids") or []
            ops = [
                {"pointer": {"id": cid, "table": "collection", "spaceId": SPACE_ID},
                 "path": ["format", "automation_ids"], "command": "listRemove", "args": {"id": aid}},
                {"pointer": {"id": aid, "table": "automation", "spaceId": SPACE_ID},
                 "path": [], "command": "update",
                 "args": {"alive": False, "last_edited_time": now,
                          "last_edited_by_id": USER_ID, "last_edited_by_table": "notion_user"}},
                {"pointer": {"id": cid, "table": "collection", "spaceId": SPACE_ID},
                 "path": [], "command": "update",
                 "args": {"last_edited_time": now, "last_edited_by_id": USER_ID, "last_edited_by_table": "notion_user"}},
                {"pointer": {"table": "block", "id": db_block, "spaceId": SPACE_ID},
                 "path": [], "command": "update",
                 "args": {"last_edited_time": now, "last_edited_by_id": USER_ID, "last_edited_by_table": "notion_user"}},
            ]
            for act in action_ids:
                ops.append({"pointer": {"id": act, "table": "automation_action", "spaceId": SPACE_ID},
                            "path": [], "command": "update", "args": {"alive": False}})
            save_transactions(page, ops, "deactivateAutomation")
            print(f"  deactivated {aid} (source={db_block})")


def main() -> int:
    deactivate = "--deactivate" in sys.argv
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp("http://localhost:9222")
        page = [pg for pg in browser.contexts[0].pages if "notion.so" in pg.url][-1]
        print(f"connected to: {page.url}")

        if deactivate:
            print("== deactivating existing automations ==")
            deactivate_all(page)
            return 0

        # Pre-resolve all collection ids
        coll = {}
        for k, b in [("APP", APP_DB), ("MGT", MGT_DB), ("HIS", HIS_DB)]:
            coll[b] = resolve_collection_id(page, b)
            print(f"  {k} {b} -> collection {coll[b]}")

        # Resolve HIS event-type property id once
        his_event_pid = resolve_his_event_type_prop_id(page)
        print(f"  HIS 이벤트 유형 prop id: {his_event_pid}")

        print("\n== creating automations ==")
        created = []
        for rule in RULES:
            print(f"-- {rule['id']} {rule['name']} --")
            # Resolve placeholder EVENT_TYPE prop id
            selects = dict(rule.get("selects") or {})
            if "EVENT_TYPE" in selects:
                selects[his_event_pid] = selects.pop("EVENT_TYPE")
            # Resolve formula_refs_tpl (needs source_coll)
            formula_refs = {}
            for tpl in (rule.get("formula_refs_tpl") or []):
                target_pid, kind, src_pid, src_name = tpl
                src_coll = coll[rule["source"]] if kind == "source" else None
                formula_refs[target_pid] = (src_coll, src_pid, src_name)
            ops, auto_id, action_id = build_create_ops(
                source_coll=coll[rule["source"]],
                source_block=rule["source"],
                target_coll=coll[rule["target"]],
                title_text=rule["title"],
                name=rule["name"],
                trigger=rule["trigger"],
                selects=selects,
                source_refs=rule.get("source_refs") or {},
                formula_refs=formula_refs,
                trigger_page_refs=rule.get("trigger_page_refs") or [],
                page_creator_refs=rule.get("page_creator_refs") or [],
                prop_filters=rule.get("prop_filters") or [],
            )
            save_transactions(page, ops, "sdk.createAddPageAutomation")
            print(f"   OK automation_id={auto_id}")
            created.append((rule["id"], auto_id))

        # Persist for test/cleanup
        from pathlib import Path
        Path("/tmp/pw/automations_created.json").write_text(
            json.dumps(created, ensure_ascii=False, indent=2)
        )
        print(f"\nsaved registry: /tmp/pw/automations_created.json ({len(created)} entries)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
