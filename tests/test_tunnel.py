import os
import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path

from gi.repository import GLib

from ssh_wallet.launcher import Command
from ssh_wallet.model import Forward, Host
from ssh_wallet.tunnel import TunnelManager, build_tunnel_command, exit_message

ASKPASS = Path("/opt/wallet/bin/ssh-wallet-askpass")
ROOT = Path(__file__).resolve().parent.parent


class BuildTunnelCommandTest(unittest.TestCase):
    def test_background_ssh_with_forwards_and_no_terminal(self):
        host = Host(name="pks2", host="2001:db8::1", user="student", id="id-2",
                    forwards=[Forward("L", 5901, "localhost", 5901), Forward("R", 8080, "fe80::1", 80)])

        command = build_tunnel_command(host, has_password=False, askpass_path=ASKPASS)

        self.assertEqual(command.argv, [
            "ssh", "-p", "22",
            "-N", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30", "-o", "ServerAliveCountMax=3",
            "-L", "5901:localhost:5901", "-R", "8080:[fe80::1]:80",
            "--", "student@2001:db8::1",
        ])
        self.assertEqual(command.env, {})

    def test_password_and_jump(self):
        host = Host(name="t", host="t", id="id-2", jump_id="id-1", forwards=[Forward("L", 1, "x", 1)])
        jump = Host(name="j", host="bastion", id="id-1")

        command = build_tunnel_command(host, has_password=True, askpass_path=ASKPASS,
                                       jump=jump, jump_has_password=True)

        self.assertIn("ProxyCommand=ssh -W '[%h]:%p' -p 22 -- bastion", command.argv)
        self.assertEqual(command.env["SSH_WALLET_ID"], "id-2")
        self.assertEqual(command.env["SSH_WALLET_JUMP_ID"], "id-1")


class ExitMessageTest(unittest.TestCase):
    def test_last_error_line_is_reported(self):
        stderr = "Warning: Permanently added 'x'\nbind [127.0.0.1]:5901: Address already in use\n"

        self.assertEqual(exit_message("pks2", stderr),
                         "Tunel pks2 skončil: bind [127.0.0.1]:5901: Address already in use")

    def test_busy_local_port_names_the_port_rather_than_the_generic_last_line(self):
        stderr = ("bind [127.0.0.1]:15901: Address already in use\n"
                  "channel_setup_fwd_listener_tcpip: cannot listen to port: 15901\n"
                  "Could not request local forwarding.\n")

        self.assertEqual(exit_message("t2", stderr),
                         "Tunel t2 skončil: bind [127.0.0.1]:15901: Address already in use")

    def test_unknown_host_key_gets_a_hint(self):
        message = exit_message("pks2", "Host key verification failed.\n")

        self.assertEqual(message, "Tunel pks2 skončil: Host key verification failed. "
                                  "Nejdřív se jednou připoj přes Připojit a potvrď otisk.")

    def test_no_output(self):
        self.assertEqual(exit_message("pks2", ""), "Tunel pks2 skončil.")


class FakeProcess:
    def __init__(self, pid):
        self.pid = pid
        self.terminated = False

    def terminate(self):
        self.terminated = True


class FakeSpawner:
    """Records spawned commands; the test finishes them with ``exit(pid, stderr)``."""

    def __init__(self):
        self.spawned = []
        self.watchers = {}

    def spawn(self, argv, env, stderr):
        process = FakeProcess(1000 + len(self.spawned))
        self.spawned.append((argv, env, stderr, process))
        return process

    def watch(self, pid, callback):
        self.watchers[pid] = callback

    def exit(self, process, stderr=b""):
        for argv, env, out, p in self.spawned:
            if p is process:
                out.write(stderr)
                out.flush()
        self.watchers.pop(process.pid)()


class TunnelManagerTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSpawner()
        self.manager = TunnelManager(spawn=self.fake.spawn, watch=self.fake.watch)
        self.exits = []
        self.command = Command(["ssh", "-N", "--", "h"], {"SSH_WALLET_ID": "id-1"})

    def start(self, host_id="id-1"):
        return self.manager.start(host_id, "pks2", self.command,
                                  on_exit=lambda hid, msg: self.exits.append((hid, msg)))

    def test_start_runs_the_command(self):
        self.assertTrue(self.start())

        [(argv, env, _, _)] = self.fake.spawned
        self.assertEqual((argv, env), (["ssh", "-N", "--", "h"], {"SSH_WALLET_ID": "id-1"}))
        self.assertTrue(self.manager.is_running("id-1"))

    def test_second_start_of_a_running_tunnel_is_ignored(self):
        self.start()

        self.assertFalse(self.start())
        self.assertEqual(len(self.fake.spawned), 1)

    def test_tunnel_that_dies_reports_its_error(self):
        self.start()
        process = self.fake.spawned[0][3]

        self.fake.exit(process, b"bind [127.0.0.1]:5901: Address already in use\n")

        self.assertEqual(self.exits, [("id-1", "Tunel pks2 skončil: bind [127.0.0.1]:5901: "
                                                "Address already in use")])
        self.assertFalse(self.manager.is_running("id-1"))

    def test_stopped_tunnel_reports_no_error(self):
        self.start()
        process = self.fake.spawned[0][3]

        self.manager.stop("id-1")
        self.fake.exit(process)

        self.assertTrue(process.terminated)
        self.assertEqual(self.exits, [("id-1", None)])
        self.assertFalse(self.manager.is_running("id-1"))

    def test_stop_all(self):
        self.start("id-1")
        self.start("id-2")

        self.manager.stop_all()

        self.assertTrue(all(p.terminated for *_, p in self.fake.spawned))


class RealProcessTest(unittest.TestCase):
    """The production spawn/watch pair with real processes and the GLib main loop."""

    def run_loop_until(self, condition, timeout=5):
        loop = GLib.MainLoop()
        deadline = time.monotonic() + timeout

        def check():
            if condition() or time.monotonic() > deadline:
                loop.quit()
                return False
            return True

        GLib.timeout_add(20, check)
        loop.run()

    def test_failing_process_reports_its_last_stderr_line(self):
        manager, exits = TunnelManager(), []
        command = Command(["sh", "-c", "echo 'channel_setup_fwd_listener: cannot listen' >&2; exit 255"])

        manager.start("id-1", "pks2", command, on_exit=lambda hid, msg: exits.append(msg))
        self.run_loop_until(lambda: exits)

        self.assertEqual(exits, ["Tunel pks2 skončil: channel_setup_fwd_listener: cannot listen"])

    def test_stop_terminates_the_process(self):
        manager, exits = TunnelManager(), []
        manager.start("id-1", "pks2", Command(["sleep", "30"]), on_exit=lambda hid, msg: exits.append(msg))
        pid = manager._tunnels["id-1"].process.pid

        manager.stop("id-1")
        self.run_loop_until(lambda: exits)

        self.assertEqual(exits, [None])
        self.assertFalse(Path(f"/proc/{pid}").exists())

    def test_tunnel_dies_with_the_app_process(self):
        # A parent that starts a tunnel and then exits without stopping it.
        script = textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(ROOT)!r})
            from ssh_wallet.tunnel import spawn_process
            import tempfile
            p = spawn_process(["sleep", "30"], {{}}, tempfile.TemporaryFile())
            print(p.pid, flush=True)
        """)
        out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=10)
        pid = int(out.stdout)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _alive(pid):
            time.sleep(0.05)
        self.assertFalse(_alive(pid))


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


if __name__ == "__main__":
    unittest.main()
