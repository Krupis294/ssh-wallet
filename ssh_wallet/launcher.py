"""Building the kitty + ssh command for a host and starting it."""

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ssh_wallet.model import DEFAULT_PORT, Host, bracket

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


def _identity(host: Host) -> list[str]:
    if not host.key_path:
        return []
    return ["-i", os.path.expanduser(host.key_path), "-o", "IdentitiesOnly=yes"]


def proxy_command(jump: Host) -> str:
    """ssh ProxyCommand reaching %h:%p through ``jump`` with its own port and key.

    ssh runs it through the shell and expands %-tokens first, so every value is
    shell-quoted and its % signs doubled. %h is bracketed for IPv6 targets.
    """
    values = [*_identity(jump), "--", jump.destination()]
    quoted = [shlex.quote(value).replace("%", "%%") for value in values]
    return " ".join(["ssh", "-W", "'[%h]:%p'", "-p", str(jump.port), *quoted])


def ssh_args(host: Host, jump: Host | None = None, extra: list[str] = ()) -> list[str]:
    """``ssh`` argv for ``host``: port, key, optional jump, ``extra`` options, destination."""
    args = ["ssh", "-p", str(host.port), *_identity(host)]
    if jump is not None:
        args += ["-o", f"ProxyCommand={proxy_command(jump)}"]
    return [*args, *extra, "--", host.destination()]


def display_command(host: Host, jump: Host | None = None) -> str:
    """A short ssh command line for ``host`` to paste into a shell. No password, no forwards.

    A jump with its own key cannot be written as ``-J`` (it takes no key), so
    that case falls back to the ProxyCommand the wallet itself uses.
    """
    args = ["ssh"]
    if host.port != DEFAULT_PORT:
        args += ["-p", str(host.port)]
    if host.key_path:
        args += ["-i", _quote_path(host.key_path)]
    if jump is not None and jump.key_path:
        args += ["-o", shlex.quote(f"ProxyCommand={proxy_command(jump)}")]
    elif jump is not None:
        port = f":{jump.port}" if jump.port != DEFAULT_PORT else ""
        user = f"{jump.user}@" if jump.user else ""
        args += ["-J", shlex.quote(f"{user}{bracket(jump.host)}{port}")]
    return " ".join([*args, shlex.quote(host.destination())])


def _quote_path(path: str) -> str:
    """Shell-quote ``path`` but leave a leading ``~/`` unquoted so the shell still expands it."""
    if path.startswith("~/"):
        return "~/" + shlex.quote(path[2:])
    return shlex.quote(path)


def askpass_env(host: Host, has_password: bool, jump: Host | None, jump_has_password: bool,
                askpass_path: Path) -> dict[str, str]:
    """Route ssh's prompts through ssh-wallet-askpass when any stored password can answer them."""
    if not (has_password or (jump is not None and jump_has_password)):
        return {}
    env = {"SSH_ASKPASS": str(askpass_path), "SSH_ASKPASS_REQUIRE": "force"}
    if has_password:
        env["SSH_WALLET_ID"] = host.id
    if jump is not None and jump_has_password:
        env["SSH_WALLET_JUMP_ID"] = jump.id
        env["SSH_WALLET_JUMP_HOST"] = jump.host
    return env


def build_command(host: Host, has_password: bool, askpass_path: Path = ASKPASS_PATH,
                  jump: Host | None = None, jump_has_password: bool = False) -> Command:
    argv = [
        "kitty", "--class", "ssh-wallet-session",
        # Remote machines rarely have the xterm-kitty terminfo entry.
        "-o", "term=xterm-256color",
        f"--title={host.name}",
        "sh", "-c", WRAPPER, "sh", *ssh_args(host, jump),
    ]
    return Command(argv, askpass_env(host, has_password, jump, jump_has_password, askpass_path))


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
