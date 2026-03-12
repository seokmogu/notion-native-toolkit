from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from typing import Literal, cast


CredentialKind = Literal["env", "plain", "keychain"]


@dataclass(slots=True)
class CredentialRef:
    kind: CredentialKind
    value: str | None = None
    service: str | None = None
    account: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload: dict[str, str] = {"kind": self.kind}
        if self.value is not None:
            payload["value"] = self.value
        if self.service is not None:
            payload["service"] = self.service
        if self.account is not None:
            payload["account"] = self.account
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, str] | None) -> CredentialRef | None:
        if payload is None:
            return None
        kind = payload.get("kind")
        if kind not in {"env", "plain", "keychain"}:
            raise ValueError(f"Unsupported credential kind: {kind}")
        return cls(
            kind=cast(CredentialKind, kind),
            value=payload.get("value"),
            service=payload.get("service"),
            account=payload.get("account"),
        )


def resolve_credential(ref: CredentialRef | None) -> str | None:
    if ref is None:
        return None
    if ref.kind == "plain":
        return ref.value
    if ref.kind == "env":
        return os.getenv(ref.value or "") or None
    if ref.kind == "keychain":
        if not ref.service or not ref.account:
            raise ValueError("Keychain credentials require service and account")
        return load_keychain_secret(ref.service, ref.account)
    raise ValueError(f"Unsupported credential kind: {ref.kind}")


def load_keychain_secret(service: str, account: str) -> str | None:
    command = [
        "security",
        "find-generic-password",
        "-s",
        service,
        "-a",
        account,
        "-w",
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def store_keychain_secret(service: str, account: str, secret: str) -> None:
    command = [
        "security",
        "add-generic-password",
        "-U",
        "-s",
        service,
        "-a",
        account,
        "-w",
        secret,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"Failed to store keychain secret: {message}")
