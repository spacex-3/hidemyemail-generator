import unittest
from unittest.mock import patch

from rich.console import Console

from main import SafeConsole


class SafeConsoleTests(unittest.TestCase):
    def test_log_swallows_oserror(self):
        console = SafeConsole()
        with patch.object(Console, "log", side_effect=OSError(5, "Input/output error")):
            console.log("hello")

    def test_print_swallows_oserror(self):
        console = SafeConsole()
        with patch.object(Console, "print", side_effect=OSError(5, "Input/output error")):
            console.print("hello")

    def test_rule_swallows_oserror(self):
        console = SafeConsole()
        with patch.object(Console, "rule", side_effect=OSError(5, "Input/output error")):
            console.rule("title")


if __name__ == "__main__":
    unittest.main()
