"""Exercise failure/restart contracts without requiring Docker."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


class StartupTests(unittest.TestCase):
    def test_password_xml_escape_handles_shell_and_xml_characters(self):
        function = (ROOT / "images/common/config-functions.sh").read_text()
        password = 'secret&<>"\'$(echo NOT_EXECUTED)\\tail'
        result = subprocess.run(["bash", "-c", function + '\nxml_escape "$1"', "bash", password],
                                text=True, capture_output=True, check=True)
        decoded = ET.fromstring("<value>" + result.stdout + "</value>").text
        self.assertEqual(decoded, password)

    def run_startup(self, initialized, broken_init=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mock = root / "mock"
            mock.write_text('''#!/bin/bash
set -eu
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$CALLS"
if [[ $(basename "$0") == schematool ]]; then
  case " $* " in
    *" -info "*) [[ $INITIALIZED == yes ]] ;;
    *" -initSchema "*) [[ $BROKEN_INIT == no ]] ;;
  esac
fi
''')
            mock.chmod(0o755)
            for name in ("schematool", "hdfs", "hive", "hiveserver2", "sleep"):
                (root / name).symlink_to(mock)
            calls = root / "calls"
            env = {**os.environ, "PATH": str(root) + ":" + os.environ["PATH"],
                   "CALLS": str(calls), "INITIALIZED": "yes" if initialized else "no",
                   "BROKEN_INIT": "yes" if broken_init else "no"}
            result = subprocess.run(["bash", str(ROOT / "images/hive/start.sh"), "metastore"],
                                    env=env, text=True, capture_output=True)
            return result, calls.read_text()

    def test_existing_schema_is_not_initialized_again(self):
        result, calls = self.run_startup(initialized=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("-initSchema", calls)
        self.assertIn("-validate", calls)
        self.assertIn("hive --service metastore -p 9083", calls)

    def test_empty_database_is_initialized_before_start(self):
        result, calls = self.run_startup(initialized=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(calls.index("-initSchema"), calls.index("-validate"))
        self.assertLess(calls.index("-validate"), calls.index("hive --service"))

    def test_failed_initialization_never_starts_metastore(self):
        result, calls = self.run_startup(initialized=False, broken_init=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("hive --service", calls)
        self.assertNotIn("hdfs", calls)


if __name__ == "__main__":
    unittest.main()
