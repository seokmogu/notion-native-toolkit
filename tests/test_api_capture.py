from __future__ import annotations

import json

import pytest

from notion_native_toolkit.api_capture import (
    ApiCaptureTarget,
    capture_api_surface,
    diff_api_capture_dirs,
    diff_api_indexes,
    load_api_index,
    parse_capture_target,
)


class FakeCaptureClient:
    def __init__(self, *, fail_docs: bool = False):
        self.fail_docs = fail_docs
        self.calls: list[tuple[str, str | None, str | None]] = []

    def version(self) -> str:
        return "ntn 0.17.0"

    def api_list(self, *, json_output: bool = True) -> object:
        self.calls.append(("api_list", None, None))
        return [{"method": "POST", "path": "/v1/comments"}]

    def api_docs(self, path: str, *, method: str | None = None) -> str:
        self.calls.append(("api_docs", path, method))
        if self.fail_docs:
            raise RuntimeError("docs failed")
        return f"# {method} {path}\n"

    def api_spec(self, path: str, *, method: str | None = None) -> object:
        self.calls.append(("api_spec", path, method))
        return {"path": path, "method": method}


def test_parse_capture_target_accepts_supported_formats() -> None:
    assert parse_capture_target("POST:v1/comments") == ApiCaptureTarget(
        path="v1/comments", method="POST"
    )
    assert parse_capture_target("v1/comments:POST") == ApiCaptureTarget(
        path="v1/comments", method="POST"
    )
    assert parse_capture_target("PATCH v1/pages/{page_id}") == ApiCaptureTarget(
        path="v1/pages/{page_id}", method="PATCH"
    )
    assert parse_capture_target("v1/users") == ApiCaptureTarget(
        path="v1/users", method=None
    )


def test_parse_capture_target_rejects_bad_method() -> None:
    with pytest.raises(ValueError, match="Unsupported HTTP method"):
        parse_capture_target("TRACE:v1/users")


def test_capture_api_surface_writes_index_docs_specs_and_manifest(tmp_path) -> None:
    client = FakeCaptureClient()

    report = capture_api_surface(
        client,
        tmp_path,
        [ApiCaptureTarget(path="v1/comments", method="POST")],
    )

    assert not report.errors
    assert (tmp_path / "api-index.json").exists()
    assert (tmp_path / "docs" / "post-v1__comments.md").read_text(
        encoding="utf-8"
    ) == "# POST v1/comments\n"
    assert json.loads(
        (tmp_path / "specs" / "post-v1__comments.json").read_text(encoding="utf-8")
    ) == {"path": "v1/comments", "method": "POST"}
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ntn_version"] == "ntn 0.17.0"
    assert {file_info["kind"] for file_info in manifest["files"]} == {
        "api-index",
        "docs",
        "spec",
        "manifest",
    }
    assert client.calls == [
        ("api_list", None, None),
        ("api_docs", "v1/comments", "POST"),
        ("api_spec", "v1/comments", "POST"),
    ]


def test_capture_api_surface_records_endpoint_errors(tmp_path) -> None:
    client = FakeCaptureClient(fail_docs=True)

    report = capture_api_surface(
        client,
        tmp_path,
        [ApiCaptureTarget(path="v1/comments", method="POST")],
    )

    assert report.errors == [
        {"target": "POST v1/comments", "kind": "docs", "error": "docs failed"}
    ]
    assert (tmp_path / "specs" / "post-v1__comments.json").exists()


def test_load_api_index_parses_supported_endpoint_fields(tmp_path) -> None:
    index_path = tmp_path / "api-index.json"
    _write_index(
        index_path,
        [
            {
                "method": "get",
                "path": "/v1/users",
                "summary": "List users",
                "operation_id": "listUsers",
                "tags": ["Users"],
            },
            {"method": "POST", "path": "/v1/comments", "summary": None},
        ],
    )

    endpoints = load_api_index(index_path)

    assert [endpoint.key for endpoint in endpoints] == [
        "GET /v1/users",
        "POST /v1/comments",
    ]
    assert endpoints[0].to_dict() == {
        "method": "GET",
        "path": "/v1/users",
        "summary": "List users",
        "operation_id": "listUsers",
        "tags": ["Users"],
    }
    assert endpoints[1].summary == ""


def test_load_api_index_rejects_invalid_shapes(tmp_path) -> None:
    index_path = tmp_path / "api-index.json"
    index_path.write_text(json.dumps({"method": "GET"}), encoding="utf-8")

    with pytest.raises(ValueError, match="API index must be a list"):
        load_api_index(index_path)

    _write_index(index_path, [{"path": "/v1/users"}])

    with pytest.raises(ValueError, match="missing method/path"):
        load_api_index(index_path)


def test_diff_api_indexes_reports_added_removed_and_changed(tmp_path) -> None:
    old_index = tmp_path / "old.json"
    new_index = tmp_path / "new.json"
    _write_index(
        old_index,
        [
            {
                "method": "GET",
                "path": "/v1/users",
                "summary": "Old summary",
                "operation_id": "listUsers",
                "tags": ["Users"],
            },
            {"method": "POST", "path": "/v1/comments"},
        ],
    )
    _write_index(
        new_index,
        [
            {
                "method": "GET",
                "path": "/v1/users",
                "summary": "New summary",
                "operation_id": "listUsers",
                "tags": ["Users"],
            },
            {"method": "PATCH", "path": "/v1/pages/{page_id}"},
        ],
    )

    diff = diff_api_indexes(old_index, new_index)

    assert diff.has_changes
    assert [endpoint.key for endpoint in diff.added] == ["PATCH /v1/pages/{page_id}"]
    assert [endpoint.key for endpoint in diff.removed] == ["POST /v1/comments"]
    assert [(change.before.key, change.changed_fields) for change in diff.changed] == [
        ("GET /v1/users", ["summary"])
    ]
    assert diff.to_dict()["summary"] == {"added": 1, "removed": 1, "changed": 1}


def test_diff_api_capture_dirs_reads_default_index_name(tmp_path) -> None:
    old_dir = tmp_path / "old"
    new_dir = tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    _write_index(old_dir / "api-index.json", [{"method": "GET", "path": "/v1/users"}])
    _write_index(new_dir / "api-index.json", [{"method": "GET", "path": "/v1/users"}])

    diff = diff_api_capture_dirs(old_dir, new_dir)

    assert not diff.has_changes


def _write_index(path, payload) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")
