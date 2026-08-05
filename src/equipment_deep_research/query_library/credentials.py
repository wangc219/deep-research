from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from equipment_deep_research.query_library.persistence import QueryLibraryRepository


class EncryptedCredentialStore:
    """Persist provider secrets encrypted with a local, permission-restricted key."""

    def __init__(self, repository: QueryLibraryRepository, key_path: str | Path) -> None:
        self.repository = repository
        self.key_path = Path(key_path).expanduser().resolve()

    def save(self, api_key: str) -> str:
        secret = api_key.strip()
        if not secret:
            raise ValueError("API key is empty")
        if len(secret) > 8000:
            raise ValueError("API key exceeds 8000 characters")
        encrypted = self._fernet().encrypt(secret.encode("utf-8")).decode("ascii")
        return self.repository.create_provider_credential(encrypted)

    def resolve(self, credential_id: str) -> str:
        encrypted = self.repository.get_provider_credential(credential_id)
        try:
            return self._fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("provider credential cannot be decrypted with the current key") from exc

    def _fernet(self) -> Fernet:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            key = self.key_path.read_bytes().strip()
        except FileNotFoundError:
            key = Fernet.generate_key()
            try:
                descriptor = os.open(
                    self.key_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                key = self.key_path.read_bytes().strip()
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(key + b"\n")
        os.chmod(self.key_path, 0o600)
        return Fernet(key)
