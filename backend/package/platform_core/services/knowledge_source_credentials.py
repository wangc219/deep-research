"""知识来源凭据的本地加密与解密。"""

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


def encrypt_source_secret(secret: str) -> str:
    """使用权限受限的部署密钥加密来源连接 JSON。"""
    return _fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_source_secret(encrypted_secret: str) -> str:
    """解密来源连接 JSON，密钥不匹配时给出稳定错误。"""
    try:
        return _fernet().decrypt(encrypted_secret.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("知识来源凭据无法使用当前部署密钥解密") from exc


def _fernet() -> Fernet:
    inline_key = os.getenv("KNOWLEDGE_SOURCE_CREDENTIAL_KEY", "").strip()
    if inline_key:
        return Fernet(inline_key.encode("ascii"))

    key_path = Path(
        os.getenv("KNOWLEDGE_SOURCE_CREDENTIAL_KEY_FILE", "outputs/knowledge-source-credential.key")
    ).resolve()
    key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(Fernet.generate_key())
    return Fernet(key_path.read_bytes().strip())
