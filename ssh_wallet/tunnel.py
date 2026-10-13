"""Port-forwarding tunnels: ``ssh -N`` in the background, no terminal.

Tunnels belong to the running app: they stop when it quits and, through
PR_SET_PDEATHSIG, also when it crashes. Without a terminal nothing can be
asked interactively, so a tunnel relies on a stored password or a key and an
already known host key; when ssh gives up, its last error line is reported.
"""

import ctypes
import os
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from gi.repository import GLib

from ssh_wallet.launcher import ASKPASS_PATH, Command, askpass_env, ssh_args
from ssh_wallet.model import Host

TUNNEL_OPTIONS = [
    "-N",
    # Fail instead of running without the forward (e.g. the local port is taken).
    "-o", "ExitOnForwardFailure=yes",
    # Notice a dead connection within ~90 s instead of hanging on.
    "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
]
_PR_SET_PDEATHSIG = 1


def build_tunnel_command(host: Host, has_password: bool, askpass_path: Path = ASKPASS_PATH,
                         jump: Host | None = None, jump_has_password: bool = False) -> Command:
    forwards = [arg for f in host.forwards for arg in (f"-{f.kind}", f.spec())]
    argv = ssh_args(host, jump, extra=[*TUNNEL_OPTIONS, *forwards])
    return Command(argv, askpass_env(host, has_password, jump, jump_has_password, askpass_path))


def exit_message(name: str, stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    if not lines:
        return f"Tunel {name} skončil."
    # A taken local port ends with a generic "Could not request local
    # forwarding."; the line naming the port is the useful one.
    reason = next((line for line in lines if "Address already in use" in line), lines[-1])
    message = f"Tunel {name} skončil: {reason}"
    if "Host key verification failed" in reason:
        message += " Nejdřív se jednou připoj přes Připojit a potvrď otisk."
    return message


def _die_with_parent(parent_pid: int):
    def setup():
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
        if os.getppid() != parent_pid:  # the parent died before prctl took effect
            os._exit(1)
    return setup


def spawn_process(argv: list[str], env: dict[str, str], stderr) -> subprocess.Popen:
    return subprocess.Popen(
        argv,
        env={**os.environ, **env},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=stderr,
        # No controlling terminal: askpass cannot fall back to asking on a tty.
        start_new_session=True,
        preexec_fn=_die_with_parent(os.getpid()),
    )


def watch_process(pid: int, callback) -> None:
    GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid, lambda *_: callback())


@dataclass
class _Tunnel:
    name: str
    process: object
    stderr: object
    on_exit: object
    stopping: bool = False


class TunnelManager:
    def __init__(self, spawn=spawn_process, watch=watch_process):
        self._spawn = spawn
        self._watch = watch
        self._tunnels: dict[str, _Tunnel] = {}

    def is_running(self, host_id: str) -> bool:
        return host_id in self._tunnels

    def start(self, host_id: str, name: str, command: Command, on_exit) -> bool:
        """Start a tunnel; ``on_exit(host_id, error_or_None)`` runs when it ends.

        Returns False when this host's tunnel is already running. Raises OSError
        when the command cannot be started.
        """
        if host_id in self._tunnels:
            return False
        stderr = tempfile.TemporaryFile()
        try:
            process = self._spawn(command.argv, command.env, stderr)
        except OSError:
            stderr.close()
            raise
        self._tunnels[host_id] = _Tunnel(name, process, stderr, on_exit)
        self._watch(process.pid, lambda: self._exited(host_id))
        return True

    def stop(self, host_id: str) -> None:
        if tunnel := self._tunnels.get(host_id):
            tunnel.stopping = True
            tunnel.process.terminate()

    def stop_all(self) -> None:
        for host_id in list(self._tunnels):
            self.stop(host_id)

    def _exited(self, host_id: str) -> None:
        tunnel = self._tunnels.pop(host_id)
        tunnel.stderr.seek(0)
        output = tunnel.stderr.read().decode(errors="replace")
        tunnel.stderr.close()
        tunnel.on_exit(host_id, None if tunnel.stopping else exit_message(tunnel.name, output))
