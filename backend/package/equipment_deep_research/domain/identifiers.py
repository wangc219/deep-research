from __future__ import annotations

from pathlib import Path
import re
import unicodedata


_INTERNAL_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*", re.ASCII)
_MAX_INTERNAL_IDENTIFIER_LENGTH = 128


def validate_internal_identifier(
    value: str,
    *,
    field_name: str = "identifier",
    max_length: int = _MAX_INTERNAL_IDENTIFIER_LENGTH,
) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{field_name} must be at most {max_length} characters")
    if value in {".", ".."}:
        raise ValueError(f"{field_name} must not be a path traversal component")
    if Path(value).is_absolute() or "/" in value or "\\" in value:
        raise ValueError(f"{field_name} must not contain a path")
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    if _INTERNAL_IDENTIFIER.fullmatch(value) is None:
        raise ValueError(
            f"{field_name} must start with an ASCII letter or digit and contain only "
            "ASCII letters, digits, dots, underscores, or hyphens"
        )
    return value


def safe_identifier_path(
    parent: str | Path,
    identifier: str,
    *,
    suffix: str = "",
    field_name: str = "identifier",
) -> Path:
    validated = validate_internal_identifier(identifier, field_name=field_name)
    parent_path = Path(parent)
    if parent_path.is_symlink():
        raise ValueError(f"{field_name} parent directory must not be a symlink")
    resolved_parent = parent_path.resolve(strict=True)
    candidate = parent_path / f"{validated}{suffix}"
    if candidate.is_symlink():
        raise ValueError(f"{field_name} path must not be a symlink")
    if candidate.resolve(strict=False).parent != resolved_parent:
        raise ValueError(f"{field_name} path must stay within its parent directory")
    return candidate
