from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHROME_EPOCH_OFFSET_SECONDS = 11_644_473_600
MACOS_CHROME_USER_DATA_DIR = (
    Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
)
NOTION_COOKIE_DOMAIN = "notion.so"


class ChromeCookieSyncError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ChromeCookieSyncResult:
    source_cookie_db: Path
    storage_state_path: Path
    cookies_synced: int
    token_v2_present: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "source_cookie_db": str(self.source_cookie_db),
            "storage_state_path": str(self.storage_state_path),
            "cookies_synced": self.cookies_synced,
            "token_v2_present": self.token_v2_present,
        }


def sync_chrome_cookies_to_storage_state(
    storage_state_path: str | Path,
    *,
    chrome_profile: str | None = None,
    chrome_user_data_dir: str | Path | None = None,
    domain_contains: str = NOTION_COOKIE_DOMAIN,
) -> ChromeCookieSyncResult:
    source_db = find_chrome_cookie_db(
        chrome_profile=chrome_profile,
        chrome_user_data_dir=chrome_user_data_dir,
        domain_contains=domain_contains,
    )
    cookies = export_chrome_cookies(
        source_db,
        domain_contains=domain_contains,
    )
    if not cookies:
        raise ChromeCookieSyncError(
            f"No Chrome cookies found for domain containing {domain_contains!r}"
        )
    target = Path(storage_state_path).expanduser()
    _write_storage_state(target, cookies, domain_contains=domain_contains)
    return ChromeCookieSyncResult(
        source_cookie_db=source_db,
        storage_state_path=target,
        cookies_synced=len(cookies),
        token_v2_present=any(cookie.get("name") == "token_v2" for cookie in cookies),
    )


def find_chrome_cookie_db(
    *,
    chrome_profile: str | None = None,
    chrome_user_data_dir: str | Path | None = None,
    domain_contains: str = NOTION_COOKIE_DOMAIN,
) -> Path:
    user_data_dir = Path(chrome_user_data_dir).expanduser() if chrome_user_data_dir else MACOS_CHROME_USER_DATA_DIR
    if chrome_profile:
        profile_path = Path(chrome_profile).expanduser()
        if not profile_path.is_absolute():
            profile_path = user_data_dir / chrome_profile
        db_path = profile_path / "Cookies"
        if not db_path.exists():
            raise ChromeCookieSyncError(f"Chrome Cookies DB not found: {db_path}")
        return db_path

    candidates = [user_data_dir / "Default" / "Cookies"]
    candidates.extend(sorted(user_data_dir.glob("Profile */Cookies")))
    existing = [candidate for candidate in candidates if candidate.exists()]
    for candidate in existing:
        if _cookie_db_has_domain(candidate, domain_contains=domain_contains):
            return candidate
    if existing:
        return existing[0]
    raise ChromeCookieSyncError(f"Chrome profile Cookies DB not found under {user_data_dir}")


def export_chrome_cookies(
    cookie_db: str | Path,
    *,
    domain_contains: str = NOTION_COOKIE_DOMAIN,
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory() as temp_dir:
        copied_db = Path(temp_dir) / "Cookies"
        shutil.copy2(Path(cookie_db).expanduser(), copied_db)
        with sqlite3.connect(copied_db) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                select host_key, name, value, encrypted_value, path, expires_utc,
                       is_secure, is_httponly, has_expires, is_persistent, samesite
                from cookies
                where host_key like ?
                order by host_key, name, path
                """,
                (f"%{domain_contains}%",),
            ).fetchall()
    return [_row_to_playwright_cookie(row) for row in rows]


def _cookie_db_has_domain(cookie_db: Path, *, domain_contains: str) -> bool:
    with tempfile.TemporaryDirectory() as temp_dir:
        copied_db = Path(temp_dir) / "Cookies"
        shutil.copy2(cookie_db, copied_db)
        with sqlite3.connect(copied_db) as connection:
            count = connection.execute(
                "select count(*) from cookies where host_key like ?",
                (f"%{domain_contains}%",),
            ).fetchone()[0]
    return bool(count)


def _row_to_playwright_cookie(row: sqlite3.Row) -> dict[str, Any]:
    host_key = str(row["host_key"])
    value = str(row["value"] or "")
    if not value:
        value = _decrypt_chrome_value(host_key, bytes(row["encrypted_value"] or b""))
    return {
        "name": str(row["name"]),
        "value": value,
        "domain": host_key,
        "path": str(row["path"] or "/"),
        "expires": _chrome_expires_to_unix_seconds(
            int(row["expires_utc"] or 0),
            has_expires=bool(row["has_expires"]),
            is_persistent=bool(row["is_persistent"]),
        ),
        "httpOnly": bool(row["is_httponly"]),
        "secure": bool(row["is_secure"]),
        "sameSite": _playwright_same_site(int(row["samesite"] or -1)),
    }


def _decrypt_chrome_value(host_key: str, encrypted_value: bytes) -> str:
    if not encrypted_value:
        return ""
    encrypted_payload = encrypted_value[3:] if encrypted_value[:3] in {b"v10", b"v11"} else encrypted_value
    key = _macos_chrome_cookie_key()
    plaintext = _aes_cbc_decrypt(key, encrypted_payload)
    host_hash = hashlib.sha256(host_key.encode("utf-8")).digest()
    if plaintext.startswith(host_hash):
        plaintext = plaintext[len(host_hash) :]
    return plaintext.decode("utf-8", errors="replace")


def _macos_chrome_cookie_key() -> bytes:
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ChromeCookieSyncError(
            "Could not read Chrome Safe Storage from macOS Keychain"
        )
    passphrase = result.stdout.rstrip(b"\n")
    return hashlib.pbkdf2_hmac("sha1", passphrase, b"saltysalt", 1003, 16)


def _aes_cbc_decrypt(key: bytes, ciphertext: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError:
        plaintext = _aes_cbc_decrypt_with_openssl(key, ciphertext)
    else:
        decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
    return _strip_pkcs7_padding(plaintext)


def _aes_cbc_decrypt_with_openssl(key: bytes, ciphertext: bytes) -> bytes:
    result = subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-128-cbc",
            "-K",
            key.hex(),
            "-iv",
            (b" " * 16).hex(),
            "-nopad",
        ],
        input=ciphertext,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ChromeCookieSyncError("OpenSSL could not decrypt Chrome cookie data")
    return result.stdout


def _strip_pkcs7_padding(value: bytes) -> bytes:
    if not value:
        return value
    padding = value[-1]
    if 1 <= padding <= 16 and value.endswith(bytes([padding]) * padding):
        return value[:-padding]
    raise ChromeCookieSyncError("Chrome cookie data had invalid padding")


def _chrome_expires_to_unix_seconds(
    expires_utc: int,
    *,
    has_expires: bool,
    is_persistent: bool,
) -> int:
    if not has_expires or not is_persistent or expires_utc <= 0:
        return -1
    return max(0, int((expires_utc / 1_000_000) - CHROME_EPOCH_OFFSET_SECONDS))


def _playwright_same_site(value: int) -> str:
    if value == 0:
        return "None"
    if value == 2:
        return "Strict"
    return "Lax"


def _write_storage_state(
    target: Path,
    cookies: list[dict[str, Any]],
    *,
    domain_contains: str,
) -> None:
    state = _read_existing_storage_state(target)
    existing = [
        cookie
        for cookie in state.get("cookies", [])
        if isinstance(cookie, dict)
        and domain_contains not in str(cookie.get("domain") or "")
    ]
    state["cookies"] = [*existing, *cookies]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_existing_storage_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"cookies": [], "origins": []}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {"cookies": [], "origins": []}
    cookies = payload.get("cookies")
    origins = payload.get("origins")
    return {
        "cookies": cookies if isinstance(cookies, list) else [],
        "origins": origins if isinstance(origins, list) else [],
    }
