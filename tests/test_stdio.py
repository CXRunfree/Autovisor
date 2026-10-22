import sys
import unittest
from unittest import mock

from modules.stdio import WINDOWS_UTF8_CODEPAGE, configure_stdio


class StdioTests(unittest.TestCase):
    def test_non_windows_is_noop(self):
        stream = mock.Mock()
        with mock.patch.object(sys, "platform", "darwin"), mock.patch.object(
            sys, "stdout", stream
        ), mock.patch.object(sys, "stderr", stream):
            configure_stdio()
        stream.reconfigure.assert_not_called()

    def test_windows_reconfigures_utf8(self):
        stdout = mock.Mock()
        stderr = mock.Mock()
        kernel32 = mock.Mock()
        fake_ctypes = mock.Mock()
        fake_ctypes.windll.kernel32 = kernel32
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(
            sys, "stdout", stdout
        ), mock.patch.object(sys, "stderr", stderr), mock.patch.dict(
            sys.modules, {"ctypes": fake_ctypes}
        ):
            configure_stdio()
        stdout.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
        stderr.reconfigure.assert_called_once_with(encoding="utf-8", errors="replace")
        kernel32.SetConsoleOutputCP.assert_called_once_with(WINDOWS_UTF8_CODEPAGE)
        kernel32.SetConsoleCP.assert_called_once_with(WINDOWS_UTF8_CODEPAGE)

    def test_windows_without_reconfigure_still_sets_codepage(self):
        stream = mock.Mock(spec=[])
        kernel32 = mock.Mock()
        fake_ctypes = mock.Mock()
        fake_ctypes.windll.kernel32 = kernel32
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(
            sys, "stdout", stream
        ), mock.patch.object(sys, "stderr", stream), mock.patch.dict(
            sys.modules, {"ctypes": fake_ctypes}
        ):
            configure_stdio()
        kernel32.SetConsoleOutputCP.assert_called_once_with(WINDOWS_UTF8_CODEPAGE)


if __name__ == "__main__":
    unittest.main()
