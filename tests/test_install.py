import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InstallScriptTest(unittest.TestCase):
    def test_installs_symlink_and_desktop_entry_into_home(self):
        with tempfile.TemporaryDirectory() as home:
            env = {k: v for k, v in os.environ.items() if k != "XDG_DATA_HOME"}
            env["HOME"] = home

            subprocess.run(["sh", str(ROOT / "install.sh")], env=env, check=True,
                           capture_output=True)

            link = Path(home, ".local/bin/ssh-wallet")
            self.assertEqual(link.resolve(), ROOT / "bin/ssh-wallet")
            desktop = Path(home, ".local/share/applications/io.github.krupis294.SshWallet.desktop")
            self.assertIn(f"Exec={ROOT}/bin/ssh-wallet\n", desktop.read_text())


if __name__ == "__main__":
    unittest.main()
