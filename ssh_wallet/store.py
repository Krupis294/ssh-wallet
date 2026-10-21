"""Persistence of host entries in a JSON file. Passwords never go here."""

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ssh_wallet.model import Forward, Host

# Version 2 keeps hosts in the user's order; version 1 files are read sorted by name.
FORMAT_VERSION = 2
_SUPPORTED_VERSIONS = (1, 2)
_STRING_FIELDS = ("id", "name", "host", "user", "key_path", "note")


def default_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(config_home) / "ssh-wallet" / "hosts.json"


@dataclass
class LoadResult:
    hosts: list[Host]
    # Set when the existing file was unreadable and has been moved aside.
    backup_path: Path | None = None


class HostStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> LoadResult:
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return LoadResult([])
        try:
            return LoadResult(_parse(text))
        except (ValueError, TypeError, KeyError):
            return LoadResult([], self._move_aside())

    def save(self, hosts: list[Host]) -> None:
        """Write atomically: a crash leaves either the old or the new file, never half of one."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        data = {"version": FORMAT_VERSION, "hosts": [_to_dict(h) for h in hosts]}
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".hosts-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _move_aside(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.bak-{stamp}")
        n = 1
        while backup.exists():
            backup = self.path.with_name(f"{self.path.name}.bak-{stamp}-{n}")
            n += 1
        self.path.rename(backup)
        return backup


def _to_dict(host: Host) -> dict:
    d = asdict(host)
    return {"id": d.pop("id"), **d}


def _parse(text: str) -> list[Host]:
    data = json.loads(text)
    if not isinstance(data, dict) or data.get("version") not in _SUPPORTED_VERSIONS:
        raise ValueError("unsupported file format")
    if not isinstance(data["hosts"], list):
        raise TypeError("hosts must be a list")
    hosts = [_from_dict(entry) for entry in data["hosts"]]
    if data["version"] == 1:
        hosts.sort(key=lambda h: h.name.casefold())
    return hosts


def _int(value) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("expected an integer")
    return value


def _str(value) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


def _from_dict(entry: dict) -> Host:
    # jump_id and forwards came later; files written before them lack the keys.
    forwards = entry.get("forwards", [])
    if not isinstance(forwards, list):
        raise TypeError("forwards must be a list")
    return Host(
        port=_int(entry["port"]),
        jump_id=_str(entry.get("jump_id", "")),
        forwards=[Forward(kind=_str(f["kind"]), port=_int(f["port"]),
                          dest_host=_str(f["dest_host"]), dest_port=_int(f["dest_port"]))
                  for f in forwards],
        **{key: _str(entry[key]) for key in _STRING_FIELDS},
    )
