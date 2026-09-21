import io
import unittest
from unittest import mock

from core.view import _console_print


class ConsoleOutputTest(unittest.TestCase):
    def test_console_print_replaces_unencodable_redirected_output(self):
        buffer = io.BytesIO()
        redirected_stdout = io.TextIOWrapper(buffer, encoding="cp1252")

        with mock.patch("sys.stdout", redirected_stdout):
            _console_print("banner block \u2588")
            redirected_stdout.flush()

        output = buffer.getvalue().decode("cp1252").replace("\r\n", "\n")
        self.assertEqual(output, "banner block ?\n")


if __name__ == "__main__":
    unittest.main()
