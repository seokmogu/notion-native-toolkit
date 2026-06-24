from __future__ import annotations

import json
from pathlib import Path

from notion_native_toolkit.browser_state import find_storage_state_cookie


def test_find_storage_state_cookie_prefers_notion_com_session(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps(
            {
                "cookies": [
                    {
                        "name": "token_v2",
                        "value": "expired-so",
                        "domain": ".www.notion.so",
                        "path": "/",
                        "expires": 1,
                    },
                    {
                        "name": "token_v2",
                        "value": "fresh-com",
                        "domain": ".app.notion.com",
                        "path": "/",
                        "expires": 1_813_817_538,
                    },
                ],
                "origins": [],
            }
        ),
        encoding="utf-8",
    )

    assert find_storage_state_cookie(state, "token_v2") == "fresh-com"
