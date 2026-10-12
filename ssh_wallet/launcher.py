"""Building the kitty + ssh command for a host and starting it."""

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ssh_wallet.model import Host

ASKPASS_PATH = Path(__file__).resolve().parent.parent / "bin" / "ssh-wallet-askpass"

# Runs "$@" (the ssh command). ssh exits with 255 when it cannot connect or
# authenticate; keep the window open then so the error stays readable.
WRAPPER = """\
"$@"
rc=$?
if [ "$rc" -eq 255 ]; then
  printf '\\n%s\\n' 'Spojení selhalo (ssh skončil s kódem 255). Stiskni Enter pro zavření okna.'
  read -r _
fi
exit "$rc"
"""


@dataclass(frozen=True)
class Command:
    argv: list[str]
    # Variables added on top of the current environment.
    env: dict[str, str] = field(default_factory=dict)


class LaunchError(Exception):
    pass


def build_command(host: Host, has_password: bool, askpass_path: Path = ASKPASS_PATH) -> Command:
    ssh = ["ssh", "-p", str(host.port)]
    if host.key_path:
        ssh += ["-i", os.path.expanduser(host.key_path), "-o", "IdentitiesOnly=yes"]
    ssh += ["--", host.destination()]

    argv = [
        "kitty", "--class", "ssh-wallet-session",
        # Remote machines rarely have the xterm-kitty terminfo entry.
        "-o", "term=xterm-256color",
        f"--title={host.name}",
        "sh", "-c", WRAPPER, "sh", *ssh,
    ]
    env = {}
    if has_password:
        env = {
            "SSH_ASKPASS": str(askpass_path),
            "SSH_ASKPASS_REQUIRE": "force",
            "SSH_WALLET_ID": host.id,
        }
    return Command(argv, env)


def launch(command: Command, popen=subprocess.Popen) -> None:
    """Start the command detached, so it outlives the wallet window."""
    try:
        popen(
            command.argv,
            env={**os.environ, **command.env},
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as e:
        raise LaunchError(f"Nepodařilo se spustit {command.argv[0]}: {e.strerror or e}") from e
