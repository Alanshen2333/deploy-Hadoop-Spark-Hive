"""Configuration delivery, persistence and failure contracts without Hadoop JVMs."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
COMMON = ROOT / 'images/common'


class XmlEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'source'
        shutil.copytree(ROOT / 'config/hadoop', self.source)
        for path in self.source.iterdir():
            path.chmod(0o444)
        self.target = self.root / 'target'
        self.data = self.root / 'name'
        self.data.mkdir()
        self.calls = self.root / 'calls'
        mock = self.root / 'mock'
        mock.write_text('''#!/bin/bash
set -eu
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$CALLS"
if [[ $(basename "$0") == hdfs ]]; then
  if [[ $1 == getconf ]]; then printf '%s\\n' "file://$NAMEDIR"; fi
  if [[ $* == 'namenode -format '* ]]; then
    [[ ${FAIL_FORMAT:-no} == no ]] || exit 1
    mkdir -p "$NAMEDIR/current"
    touch "$NAMEDIR/current/VERSION"
  fi
fi
if [[ $(basename "$0") == timeout ]]; then [[ ${DEPENDENCY_READY:-yes} == yes ]]; fi
''')
        mock.chmod(0o755)
        for name in ('hdfs', 'yarn', 'mapred', 'timeout', 'sleep'):
            (self.root / name).symlink_to(mock)
        self.env = {**os.environ, 'PATH': str(self.root) + ':' + os.environ['PATH'],
                    'CLUSTER_CONFIG_DIR': str(self.source), 'HADOOP_CONF_DIR': str(self.target),
                    'CALLS': str(self.calls), 'NAMEDIR': str(self.data), 'CLUSTER_NAME': 'test',
                    'SERVICE_PRECONDITION': '', 'DEPENDENCY_WAIT_ATTEMPTS': '1',
                    'DEPENDENCY_WAIT_INTERVAL': '0'}

    def startup(self, role, **env):
        result = subprocess.run(['bash', str(COMMON / 'hadoop-entrypoint.sh'), role],
                                env={**self.env, **env}, text=True, capture_output=True)
        calls = self.calls.read_text() if self.calls.exists() else ''
        return result, calls

    def test_readonly_sources_are_copied_without_modification(self):
        original = {p.name: p.read_bytes() for p in self.source.iterdir()}
        result, calls = self.startup('datanode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('hdfs datanode', calls)
        for filename, content in original.items():
            self.assertEqual((self.source / filename).read_bytes(), content)
            self.assertEqual((self.target / filename).read_bytes(), content)

    def test_missing_xml_prevents_service_start(self):
        (self.source / 'yarn-site.xml').unlink()
        result, calls = self.startup('resourcemanager')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, '')

    def test_existing_namenode_is_not_formatted(self):
        (self.data / 'current').mkdir()
        (self.data / 'current/VERSION').touch()
        result, calls = self.startup('namenode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('-format', calls)
        self.assertIn('hdfs namenode\n', calls)
        self.assertIn('getconf -confKey dfs.namenode.name.dir', calls)

    def test_empty_namenode_formats_once_then_restarts(self):
        result, calls = self.startup('namenode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('namenode -format test -nonInteractive', calls)
        result, calls = self.startup('namenode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.count('-format'), 1)

    def test_nonempty_unrecognized_namenode_is_never_formatted(self):
        (self.data / 'important-data').touch()
        result, calls = self.startup('namenode')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('-format', calls)
        self.assertNotIn('hdfs namenode\n', calls)

    def test_empty_lost_found_can_be_initialized(self):
        (self.data / 'lost+found').mkdir()
        result, calls = self.startup('namenode')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('-format', calls)
        self.assertFalse((self.data / 'lost+found').exists())

    def test_nonempty_lost_found_is_preserved(self):
        (self.data / 'lost+found').mkdir()
        (self.data / 'lost+found/recovered-data').touch()
        result, calls = self.startup('namenode')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('-format', calls)
        self.assertTrue((self.data / 'lost+found/recovered-data').exists())

    def test_failed_format_never_starts_namenode(self):
        result, calls = self.startup('namenode', FAIL_FORMAT='yes')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('hdfs namenode\n', calls)

    def test_dependency_timeout_prevents_start(self):
        result, calls = self.startup('nodemanager', SERVICE_PRECONDITION='rm:8088', DEPENDENCY_READY='no')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('yarn nodemanager', calls)
        self.assertIn('Dependency timed out: rm:8088', result.stderr)

    def test_dependency_ready_starts_service(self):
        result, calls = self.startup('nodemanager', SERVICE_PRECONDITION='rm:8088')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('yarn nodemanager', calls)

    def test_unknown_role_fails(self):
        result, calls = self.startup('unknown')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(calls, '')

    def test_each_yarn_and_mapreduce_role_runs_native_command(self):
        for role, expected in [('resourcemanager', 'yarn resourcemanager'),
                               ('nodemanager', 'yarn nodemanager'),
                               ('historyserver', 'yarn historyserver'),
                               ('jobhistory', 'mapred historyserver')]:
            with self.subTest(role=role):
                result, calls = self.startup(role)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(expected, calls)

    def hive_config(self, template, password=None):
        self.hive_target = self.target / 'hive-site.xml'
        source = self.source / 'hive-site.xml'
        source.write_text(template)
        env = dict(self.env)
        if password is not None:
            secret = self.root / 'secret'
            secret.write_text(password)
            env['POSTGRES_PASSWORD_FILE'] = str(secret)
        else:
            env['POSTGRES_PASSWORD_FILE'] = str(self.root / 'missing-secret')
        return subprocess.run(['bash', '-euc', 'source "$1"; prepare_hive_config "$2"',
                               'bash', str(COMMON / 'config-functions.sh'), str(self.hive_target)],
                              env=env, text=True, capture_output=True)

    def test_secret_is_escaped_without_shell_execution_or_logging(self):
        password = 'a&<>"\'$(touch SHOULD_NOT_EXIST)\\tail@@POSTGRES_PASSWORD@@'
        self.target.mkdir()
        existing = self.target / 'hive-site.xml'
        existing.write_text('<configuration/>')
        existing.chmod(0o644)
        template = (ROOT / 'config/hive/metastore/hive-site.xml').read_text()
        result = self.hive_config(template, password)
        self.assertEqual(result.returncode, 0, result.stderr)
        props = {p.findtext('name'): p.findtext('value') for p in ET.parse(self.hive_target).findall('property')}
        self.assertEqual(props['javax.jdo.option.ConnectionPassword'], password)
        self.assertNotIn(password, result.stdout + result.stderr)
        self.assertEqual(stat.S_IMODE(self.hive_target.stat().st_mode), 0o600)
        self.assertFalse((ROOT / 'SHOULD_NOT_EXIST').exists())

    def test_missing_or_empty_secret_prevents_render(self):
        template = (ROOT / 'config/hive/metastore/hive-site.xml').read_text()
        for password in (None, ''):
            with self.subTest(password=password):
                result = self.hive_config(template, password)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.hive_target.exists())

    def test_server_config_does_not_require_database_secret(self):
        template = (ROOT / 'config/hive/server/hive-site.xml').read_text()
        result = self.hive_config(template)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.hive_target.read_text(), template)

    def test_duplicate_secret_placeholder_is_rejected(self):
        result = self.hive_config('<configuration>@@POSTGRES_PASSWORD@@@@POSTGRES_PASSWORD@@</configuration>', 'secret')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.hive_target.exists())


if __name__ == '__main__':
    unittest.main()
