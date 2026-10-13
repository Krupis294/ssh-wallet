"""The SSH host entry and its validation rules."""

import uuid
from dataclasses import dataclass, field

DEFAULT_PORT = 22


@dataclass
class Host:
    name: str
    host: str
    port: int = DEFAULT_PORT
    user: str = ""
    key_path: str = ""
    note: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self) -> None:
        self.name = self.name.strip()
        self.host = self.host.strip()
        self.user = self.user.strip()
        self.key_path = self.key_path.strip()

    def errors(self) -> list[str]:
        """Return human-readable validation errors; empty when the host is valid."""
        errors = []
        if not self.name:
            errors.append("Název nesmí být prázdný.")
        if not self.host:
            errors.append("Host nesmí být prázdný.")
        elif any(ch.isspace() for ch in self.host):
            errors.append("Host nesmí obsahovat mezery.")
        elif self.host.startswith("-"):
            errors.append("Host nesmí začínat pomlčkou.")
        if self.user.startswith("-"):
            errors.append("Username nesmí začínat pomlčkou.")
        if not 1 <= self.port <= 65535:
            errors.append("Port musí být v rozsahu 1-65535.")
        return errors

    def destination(self) -> str:
        """The ssh destination argument: ``user@host`` or just ``host``."""
        return f"{self.user}@{self.host}" if self.user else self.host

    def subtitle(self) -> str:
        # Bracket IPv6 addresses so the appended port is not read as part of them.
        host = f"[{self.host}]" if ":" in self.host else self.host
        user = f"{self.user}@" if self.user else ""
        return f"{user}{host}:{self.port}"

    def matches(self, query: str) -> bool:
        """True when every whitespace-separated term of ``query`` occurs in some field."""
        haystack = " ".join([self.name, self.host, self.user, self.note]).casefold()
        return all(term in haystack for term in query.casefold().split())
