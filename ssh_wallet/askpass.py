"""SSH_ASKPASS helper: ssh runs it for every prompt and reads the answer from stdout.

With SSH_ASKPASS_REQUIRE=force ssh routes *all* prompts here, not only the
password one. The first password prompt of an ssh process is answered with
the password stored in the keyring; a second one means the stored password
was rejected, so it and every other prompt (host key confirmation, key
passphrase, 2FA code) is asked interactively on the terminal ssh runs in.
"""

import getpass
import os
import re
import sys
import tempfile
from enum import Enum, auto
from pathlib import Path

from ssh_wallet.vault import VaultError

_PASSWORD_PROMPT = re.compile(r"password[^:]*:\s*$", re.IGNORECASE)
_MARKER_PREFIX = "askpass-"


class Action(Enum):
    USE_STORED = auto()
    RETRY = auto()
    ASK_HIDDEN = auto()
    ASK_VISIBLE = auto()


def decide(prompt: str, already_used: bool) -> Action:
    if _PASSWORD_PROMPT.search(prompt):
        return Action.RETRY if already_used else Action.USE_STORED
    if "(yes/no" in prompt:
        return Action.ASK_VISIBLE
    return Action.ASK_HIDDEN


def process_key(pid: int) -> str | None:
    """``<pid>-<start time>``, unique even when the kernel reuses the pid; None if not running."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    # The command name (field 2) may contain spaces; start time is field 22.
    fields = stat[stat.rindex(")") + 2:].split()
    return f"{pid}-{fields[19]}"


class Markers:
    """Remembers which ssh processes have already been given the stored password."""

    def __init__(self, directory: Path):
        self.directory = directory

    def _path(self, pid: int) -> Path | None:
        key = process_key(pid)
        return self.directory / f"{_MARKER_PREFIX}{key}" if key else None

    def used(self, pid: int) -> bool:
        path = self._path(pid)
        return path is not None and path.exists()

    def mark(self, pid: int) -> None:
        path = self._path(pid)
        if path:
            self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.touch()

    def prune(self) -> None:
        """Delete markers of processes that are no longer running."""
        if not self.directory.is_dir():
            return
        for marker in self.directory.glob(f"{_MARKER_PREFIX}*"):
            key = marker.name.removeprefix(_MARKER_PREFIX)
            pid = key.split("-")[0]
            if not pid.isdigit() or process_key(int(pid)) != key:
                marker.unlink(missing_ok=True)


class TtyTerminal:
    """Talks to the user through the controlling terminal (the kitty window ssh runs in)."""

    def notice(self, text: str) -> None:
        try:
            with open("/dev/tty", "w") as tty:
                tty.write(text + "\n")
        except OSError:
            pass

    def ask(self, prompt: str, echo: bool) -> str | None:
        try:
            if not echo:
                return getpass.getpass(prompt)
            # Unbuffered binary: a text-mode "r+" open fails on a tty (not seekable).
            with open("/dev/tty", "r+b", buffering=0) as tty:
                tty.write(prompt.encode())
                line = tty.readline().decode(errors="replace")
            return line.rstrip("\n") if line else None
        except (OSError, EOFError, KeyboardInterrupt):
            return None


def run(prompt, entry_id, vault, terminal, markers: Markers, ssh_pid: int) -> str | None:
    """Return the answer for ssh, or None when the user cancelled."""
    action = decide(prompt, already_used=markers.used(ssh_pid))

    if action is Action.USE_STORED and entry_id and vault is not None:
        try:
            password = vault.get(entry_id)
        except VaultError as e:
            terminal.notice(f"Heslo z keyringu nelze načíst: {e}")
            password = None
        if password is not None:
            try:
                markers.mark(ssh_pid)
            except OSError:
                pass
            return password

    if action is Action.RETRY:
        terminal.notice("Uložené heslo nebylo přijato, zadej ho ručně.")
    return terminal.ask(prompt, echo=action is Action.ASK_VISIBLE)


def markers_dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / "ssh-wallet"
    return Path(tempfile.gettempdir()) / f"ssh-wallet-{os.getuid()}"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    prompt = argv[1] if len(argv) > 1 else ""
    try:
        from ssh_wallet.vault import SecretVault

        vault = SecretVault()
    except Exception:
        vault = None
    markers = Markers(markers_dir())
    try:
        markers.prune()
    except OSError:
        pass

    # ssh forks this helper directly, so the parent is the ssh process.
    answer = run(prompt, os.environ.get("SSH_WALLET_ID"), vault, TtyTerminal(), markers, os.getppid())
    if answer is None:
        return 1
    sys.stdout.write(answer + "\n")
    return 0
