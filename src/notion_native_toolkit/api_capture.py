from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class ApiCaptureClient(Protocol):
    def version(self) -> str: ...

    def api_list(self, *, json_output: bool = True) -> object: ...

    def api_docs(self, path: str, *, method: str | None = None) -> str: ...

    def api_spec(self, path: str, *, method: str | None = None) -> object: ...


@dataclass(slots=True)
class ApiCaptureTarget:
    path: str
    method: str | None = None

    @property
    def key(self) -> str:
        method = self.method.lower() if self.method else "any"
        path = self.path.strip("/").replace("/", "__").replace("{", "").replace("}", "")
        return f"{method}-{path}"

    def to_dict(self) -> dict[str, str | None]:
        return {"path": self.path, "method": self.method}


@dataclass(slots=True)
class ApiCaptureFile:
    kind: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "path": self.path}


@dataclass(slots=True)
class ApiCaptureReport:
    output_dir: str
    captured_at: str
    ntn_version: str | None
    targets: list[ApiCaptureTarget] = field(default_factory=list)
    files: list[ApiCaptureFile] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output_dir": self.output_dir,
            "captured_at": self.captured_at,
            "ntn_version": self.ntn_version,
            "targets": [target.to_dict() for target in self.targets],
            "files": [capture_file.to_dict() for capture_file in self.files],
            "errors": self.errors,
        }


@dataclass(slots=True)
class ApiIndexEndpoint:
    method: str
    path: str
    summary: str = ""
    operation_id: str = ""
    tags: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    def to_dict(self) -> dict[str, object]:
        return {
            "method": self.method,
            "path": self.path,
            "summary": self.summary,
            "operation_id": self.operation_id,
            "tags": self.tags,
        }


@dataclass(slots=True)
class ApiIndexChange:
    before: ApiIndexEndpoint
    after: ApiIndexEndpoint
    changed_fields: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "changed_fields": self.changed_fields,
        }


@dataclass(slots=True)
class ApiCaptureDiff:
    old_index: str
    new_index: str
    added: list[ApiIndexEndpoint] = field(default_factory=list)
    removed: list[ApiIndexEndpoint] = field(default_factory=list)
    changed: list[ApiIndexChange] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def to_dict(self) -> dict[str, object]:
        return {
            "old_index": self.old_index,
            "new_index": self.new_index,
            "summary": {
                "added": len(self.added),
                "removed": len(self.removed),
                "changed": len(self.changed),
            },
            "added": [endpoint.to_dict() for endpoint in self.added],
            "removed": [endpoint.to_dict() for endpoint in self.removed],
            "changed": [change.to_dict() for change in self.changed],
        }


def parse_capture_target(value: str) -> ApiCaptureTarget:
    raw = value.strip()
    if not raw:
        raise ValueError("Capture target cannot be empty")
    if " " in raw:
        method, path = raw.split(None, 1)
        return ApiCaptureTarget(path=path.strip(), method=_normalize_method(method))
    if ":" in raw:
        first, second = raw.split(":", 1)
        if first.upper() in _HTTP_METHODS:
            return ApiCaptureTarget(
                path=second.strip(), method=_normalize_method(first)
            )
        if second.upper() in _HTTP_METHODS:
            return ApiCaptureTarget(
                path=first.strip(), method=_normalize_method(second)
            )
        if first.isalpha() and first.upper() == first:
            _normalize_method(first)
    return ApiCaptureTarget(path=raw, method=None)


def capture_api_surface(
    client: ApiCaptureClient,
    output_dir: Path,
    targets: list[ApiCaptureTarget] | None = None,
    *,
    include_docs: bool = True,
    include_specs: bool = True,
) -> ApiCaptureReport:
    output_dir.mkdir(parents=True, exist_ok=True)
    report = ApiCaptureReport(
        output_dir=str(output_dir),
        captured_at=datetime.now(UTC).isoformat(),
        ntn_version=_try_version(client),
        targets=list(targets or []),
    )

    index_payload = client.api_list(json_output=True)
    index_path = output_dir / "api-index.json"
    _write_json(index_path, index_payload)
    report.files.append(ApiCaptureFile(kind="api-index", path=str(index_path)))

    docs_dir = output_dir / "docs"
    specs_dir = output_dir / "specs"

    for target in report.targets:
        if include_docs:
            try:
                docs_dir.mkdir(parents=True, exist_ok=True)
                docs = client.api_docs(target.path, method=target.method)
                docs_path = docs_dir / f"{target.key}.md"
                docs_path.write_text(docs, encoding="utf-8")
                report.files.append(ApiCaptureFile(kind="docs", path=str(docs_path)))
            except Exception as exc:
                report.errors.append(
                    {
                        "target": _target_label(target),
                        "kind": "docs",
                        "error": str(exc),
                    }
                )
        if include_specs:
            try:
                specs_dir.mkdir(parents=True, exist_ok=True)
                spec = client.api_spec(target.path, method=target.method)
                suffix = ".json" if isinstance(spec, dict) else ".txt"
                spec_path = specs_dir / f"{target.key}{suffix}"
                if isinstance(spec, dict):
                    _write_json(spec_path, spec)
                else:
                    spec_path.write_text(str(spec), encoding="utf-8")
                report.files.append(ApiCaptureFile(kind="spec", path=str(spec_path)))
            except Exception as exc:
                report.errors.append(
                    {
                        "target": _target_label(target),
                        "kind": "spec",
                        "error": str(exc),
                    }
                )

    manifest_path = output_dir / "manifest.json"
    report.files.append(ApiCaptureFile(kind="manifest", path=str(manifest_path)))
    _write_json(manifest_path, report.to_dict())
    return report


def diff_api_capture_dirs(old_dir: Path, new_dir: Path) -> ApiCaptureDiff:
    old_index = old_dir / "api-index.json"
    new_index = new_dir / "api-index.json"
    return diff_api_indexes(old_index, new_index)


def diff_api_indexes(old_index: Path, new_index: Path) -> ApiCaptureDiff:
    old_endpoints = _index_by_key(load_api_index(old_index))
    new_endpoints = _index_by_key(load_api_index(new_index))

    added = [
        new_endpoints[key] for key in sorted(new_endpoints) if key not in old_endpoints
    ]
    removed = [
        old_endpoints[key] for key in sorted(old_endpoints) if key not in new_endpoints
    ]
    changed: list[ApiIndexChange] = []
    for key in sorted(old_endpoints.keys() & new_endpoints.keys()):
        old_endpoint = old_endpoints[key]
        new_endpoint = new_endpoints[key]
        changed_fields = _changed_endpoint_fields(old_endpoint, new_endpoint)
        if changed_fields:
            changed.append(
                ApiIndexChange(
                    before=old_endpoint,
                    after=new_endpoint,
                    changed_fields=changed_fields,
                )
            )

    return ApiCaptureDiff(
        old_index=str(old_index),
        new_index=str(new_index),
        added=added,
        removed=removed,
        changed=changed,
    )


def load_api_index(path: Path) -> list[ApiIndexEndpoint]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"API index must be a list: {path}")
    endpoints: list[ApiIndexEndpoint] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(f"API index entries must be objects: {path}")
        method = item.get("method")
        path_value = item.get("path")
        if not isinstance(method, str) or not isinstance(path_value, str):
            raise ValueError(f"API index entry missing method/path: {path}")
        tags_payload = item.get("tags", [])
        tags = (
            [str(tag) for tag in tags_payload] if isinstance(tags_payload, list) else []
        )
        endpoints.append(
            ApiIndexEndpoint(
                method=method.upper(),
                path=path_value,
                summary=_optional_str(item.get("summary")),
                operation_id=_optional_str(item.get("operation_id")),
                tags=tags,
            )
        )
    return endpoints


_HTTP_METHODS = {"GET", "POST", "PATCH", "PUT", "DELETE"}


def _normalize_method(method: str) -> str:
    normalized = method.strip().upper()
    if normalized not in _HTTP_METHODS:
        raise ValueError(f"Unsupported HTTP method: {method}")
    return normalized


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _target_label(target: ApiCaptureTarget) -> str:
    return f"{target.method or '*'} {target.path}"


def _try_version(client: ApiCaptureClient) -> str | None:
    try:
        return client.version()
    except Exception:
        return None


def _optional_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _index_by_key(endpoints: list[ApiIndexEndpoint]) -> dict[str, ApiIndexEndpoint]:
    return {endpoint.key: endpoint for endpoint in endpoints}


def _changed_endpoint_fields(
    before: ApiIndexEndpoint, after: ApiIndexEndpoint
) -> list[str]:
    changed: list[str] = []
    if before.summary != after.summary:
        changed.append("summary")
    if before.operation_id != after.operation_id:
        changed.append("operation_id")
    if before.tags != after.tags:
        changed.append("tags")
    return changed
