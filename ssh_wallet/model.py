"""The SSH host entry and its validation rules."""

import uuid
from dataclasses import dataclass, field

DEFAULT_PORT = 22
FORWARD_KINDS = ("L", "R")


def _bracket(host: str) -> str:
    """IPv6 addresses go in brackets wherever a port follows them."""
    return f"[{host}]" if ":" in host else host


@dataclass
class Forward:
    """A port forward: ``L`` (local port to remote destination) or ``R`` (the reverse)."""

    kind: str
    port: int
    dest_host: str
    dest_port: int

    def __post_init__(self) -> None:
        self.dest_host = self.dest_host.strip()

    def errors(self) -> list[str]:
        errors = []
        if self.kind not in FORWARD_KINDS:
            errors.append("Typ musí být L nebo R.")
        if not 1 <= self.port <= 65535:
            errors.append("Port musí být v rozsahu 1-65535.")
        if not self.dest_host:
            errors.append("Cílový host nesmí být prázdný.")
        elif any(ch.isspace() for ch in self.dest_host):
            errors.append("Cílový host nesmí obsahovat mezery.")
        if not 1 <= self.dest_port <= 65535:
            errors.append("Cílový port musí být v rozsahu 1-65535.")
        return errors

    def spec(self) -> str:
        """The argument of ssh -L / -R."""
        return f"{self.port}:{_bracket(self.dest_host)}:{self.dest_port}"

    def describe(self) -> str:
        return f"{self.kind} {self.port} → {_bracket(self.dest_host)}:{self.dest_port}"


@dataclass
class Host:
    name: str
    host: str
    port: int = DEFAULT_PORT
    user: str = ""
    key_path: str = ""
    note: str = ""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # id of another saved host to reach this one through (ssh ProxyCommand).
    jump_id: str = ""
    forwards: list[Forward] = field(default_factory=list)

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
        if self.jump_id and self.jump_id == self.id:
            errors.append("Host nemůže být svým vlastním jump serverem.")
        for n, forward in enumerate(self.forwards, start=1):
            errors += [f"Přesměrování {n}: {e}" for e in forward.errors()]
        return errors

    def destination(self) -> str:
        """The ssh destination argument: ``user@host`` or just ``host``."""
        return f"{self.user}@{self.host}" if self.user else self.host

    def subtitle(self) -> str:
        user = f"{self.user}@" if self.user else ""
        return f"{user}{_bracket(self.host)}:{self.port}"

    def matches(self, query: str) -> bool:
        """True when every whitespace-separated term of ``query`` occurs in some field."""
        haystack = " ".join([self.name, self.host, self.user, self.note]).casefold()
        return all(term in haystack for term in query.casefold().split())
