from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class SourceWhitelist:
    allowed_domains: frozenset[str]

    @classmethod
    def load(cls, path: str | Path) -> "SourceWhitelist":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        domains: set[str] = set()
        for source in data.get("sources", []):
            domains.update(str(domain).lower() for domain in source.get("allowed_domains", []))
        return cls(allowed_domains=frozenset(domains))

    def allows(self, url: str) -> bool:
        host = _host(url)
        if not host:
            return False
        return any(host == domain or host.endswith(f".{domain}") for domain in self.allowed_domains)

    def host_for(self, url: str) -> str:
        return _host(url)


def _host(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower()
