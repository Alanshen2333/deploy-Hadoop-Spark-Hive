"""Validate authoritative XML and Compose delivery, without a Docker daemon."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = ('CORE_CONF_', 'HDFS_CONF_', 'YARN_CONF_', 'MAPRED_CONF_', 'HIVE_SITE_CONF_')


class SourceConfigTests(unittest.TestCase):
    def test_xml_sources_are_valid_and_properties_unique(self):
        files = list((ROOT / 'config').rglob('*.xml')) + list((ROOT / 'deployments/swarm/overrides').glob('*.xml'))
        self.assertGreaterEqual(len(files), 10)
        for path in files:
            with self.subTest(path=path):
                tree = ET.parse(path).getroot()
                self.assertEqual(tree.tag, 'configuration')
                names = [prop.findtext('name') for prop in tree.findall('property')]
                self.assertEqual(len(names), len(set(names)))
                self.assertTrue(all(names))
                self.assertTrue(all(prop.find('value') is not None for prop in tree.findall('property')))

    def test_persistent_directories_are_explicit_in_xml(self):
        def props(filename):
            return {p.findtext('name'): p.findtext('value') for p in ET.parse(ROOT / 'config/hadoop' / filename).findall('property')}
        self.assertEqual(props('hdfs-site.xml')['dfs.namenode.name.dir'], 'file:///hadoop/dfs/name')
        self.assertEqual(props('hdfs-site.xml')['dfs.datanode.data.dir'], 'file:///hadoop/dfs/data')
        self.assertEqual(props('yarn-site.xml')['yarn.timeline-service.leveldb-timeline-store.path'], '/hadoop/yarn/timeline')
        self.assertFalse((ROOT / 'config/hadoop.env').exists())

    def test_compose_delivers_readonly_xml_and_preserves_volume_identity(self):
        if shutil.which('docker-compose'):
            command = ['docker-compose']
        elif shutil.which('docker'):
            command = ['docker', 'compose']
        else:
            self.skipTest('Docker Compose CLI unavailable')
        probe = subprocess.run(command + ['version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode != 0:
            self.skipTest('Docker Compose plugin unavailable')
        cfg = json.loads(subprocess.check_output(command + ['-p', 'deploy-hadoop-spark-hive', '-f',
                         str(ROOT / 'deployments/compose/docker-compose.yml'), 'config', '--format', 'json'], text=True))
        self.assertEqual(set(cfg['services']), {'namenode', 'datanode', 'resourcemanager', 'nodemanager',
                                               'historyserver', 'spark-master', 'spark-worker', 'hive-server', 'postgres'})
        for name, svc in cfg['services'].items():
            self.assertFalse(any(key.startswith(PREFIXES) for key in svc['environment']))
            self.assertNotIn('POSTGRES_PASSWORD', svc['environment'])
            if name == 'postgres':
                continue
            self.assertIn('entrypoint', svc)
            mount = next(m for m in svc['volumes'] if m['target'] == '/etc/cluster')
            self.assertEqual(mount['source'], str(ROOT / 'config'))
            self.assertTrue(mount['read_only'])
            self.assertEqual(svc['environment']['CLUSTER_CONFIG_DIR'], '/etc/cluster/hadoop')
            for mount in svc['volumes']:
                if mount['type'] == 'bind':
                    self.assertTrue(Path(mount['source']).exists(), mount)
        for key in ('hadoop_namenode', 'hadoop_datanode', 'hadoop_historyserver', 'pg_data'):
            self.assertEqual(cfg['volumes'][key]['name'], 'deploy-hadoop-spark-hive_' + key)
        self.assertEqual(cfg['networks']['hadoop-spark-hive']['name'], 'deploy-hadoop-spark-hive_hadoop-spark-hive')
        for name in ('postgres', 'hive-server', 'spark-master', 'spark-worker'):
            self.assertEqual(cfg['services'][name]['secrets'][0]['source'], 'postgres_password')


if __name__ == '__main__':
    unittest.main()
