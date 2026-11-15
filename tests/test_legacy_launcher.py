"""The nativehtmlkit-host console script must hand control to the native host."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from nativehtmlkit import launcher


class LauncherTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "exec handoff is POSIX-only")
    def test_posix_wrapper_execs_host_so_signals_reach_it(self):
        fake = Path("/opt/ui4me/nativehtmlkit-host")
        with mock.patch.object(launcher, "host_binary", return_value=fake), \
                mock.patch.object(sys, "argv", ["nativehtmlkit-host", "run", "--app", "a b/app.toml"]), \
                mock.patch.object(launcher.os, "execve", side_effect=SystemExit(0)) as execve, \
                mock.patch.object(launcher.subprocess, "call") as call:
            with self.assertRaises(SystemExit):
                launcher.main()
        # execve: the host gets the same diagnostics mapping as every launch path (FR-PY-01).
        execve.assert_called_once()
        self.assertEqual(execve.call_args[0][:2], (str(fake), [str(fake), "run", "--app", "a b/app.toml"]))
        call.assert_not_called()

    def test_windows_wrapper_waits_and_returns_host_status(self):
        fake = Path("C:/ui4me/nativehtmlkit-host.exe")
        with mock.patch.object(launcher, "host_binary", return_value=fake), \
                mock.patch.object(sys, "argv", ["nativehtmlkit-host", "--version"]), \
                mock.patch.object(launcher.os, "name", "nt"), \
                mock.patch.object(launcher.subprocess, "call", return_value=3) as call:
            self.assertEqual(launcher.main(), 3)
        call.assert_called_once()
        self.assertEqual(call.call_args[0][0], [str(fake), "--version"])

    def test_no_arguments_prints_usage(self):
        with mock.patch.object(sys, "argv", ["nativehtmlkit-host"]):
            self.assertEqual(launcher.main(), 2)


if __name__ == "__main__":
    unittest.main()
