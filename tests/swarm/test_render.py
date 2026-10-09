import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[2] / "deployments/swarm"
spec = importlib.util.spec_from_file_location("render", ROOT / "render.py")
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


class SwarmRenderTests(unittest.TestCase):
    def setUp(self):
        self.cfg = render.load_inventory(ROOT / "cluster.example.json")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output = Path(self.tmp.name)

    def inventory(self, cfg):
        path = self.output / "inventory.json"
        path.write_text(json.dumps(cfg))
        return render.load_inventory(path)

    def test_stable_identity_and_placement(self):
        stack = render.render(self.cfg, self.output)
        for w in self.cfg["workers"]:
            for prefix in ("datanode", "nodemanager", "spark"):
                name = f"{prefix}-{w['id']}"
                svc = stack["services"][name]
                self.assertEqual(svc["hostname"], name)
                self.assertEqual(svc["deploy"]["replicas"], 1)
                self.assertEqual(svc["deploy"]["placement"]["constraints"],
                                 [f"node.hostname == {w['node']}"])
                self.assertEqual(svc["volumes"][0]["source"], name)
        # DNSRR cannot be combined with published ingress ports.
        for svc in stack["services"].values():
            self.assertEqual(svc["deploy"]["endpoint_mode"], "dnsrr")
            self.assertTrue(all(p["mode"] == "host" for p in svc.get("ports", [])))
            self.assertNotIn("build", svc)
            self.assertNotIn("depends_on", svc)
            self.assertNotIn("container_name", svc)
            self.assertTrue(all(v["type"] == "volume" for v in svc.get("volumes", [])))

    def test_expansion_preserves_existing_volumes(self):
        first = render.render(self.cfg, self.output)
        extended = copy.deepcopy(self.cfg)
        extended["workers"].append({"id": "worker-3", "node": "worker-3"})
        second = render.render(extended, self.output)
        for key in first["services"]:
            self.assertEqual(first["services"][key], second["services"][key])
        self.assertTrue(set(first["volumes"]) < set(second["volumes"]))

    def test_secrets_and_remote_metastore(self):
        stack = render.render(self.cfg, self.output)
        self.assertEqual(stack["secrets"]["postgres_password"]["external"], True)
        for name, svc in stack["services"].items():
            self.assertNotIn("POSTGRES_PASSWORD", svc["environment"])
            self.assertNotIn("HIVE_SITE_CONF_javax_jdo_option_ConnectionPassword", svc["environment"])
            if name not in ("postgres", "hive-metastore"):
                self.assertNotIn("secrets", svc)
        hive = ET.parse(self.output / "hive-site.xml")
        props = {p.findtext("name"): p.findtext("value") for p in hive.findall("property")}
        self.assertEqual(props["hive.metastore.uris"], "thrift://hive-metastore:9083")
        self.assertFalse(any("jdo" in name for name in props))

    def test_configs_are_versioned_and_xml_valid(self):
        first = render.render(self.cfg, self.output)
        for path in self.output.glob("*.xml"):
            ET.parse(path)
        self.cfg["hdfs_replication"] = 1
        second = render.render(self.cfg, self.output)
        self.assertNotEqual(set(first["configs"]), set(second["configs"]))
        for ref in second["services"]["spark-master"]["configs"]:
            self.assertIn(ref["source"], second["configs"])
            self.assertTrue(Path(second["configs"][ref["source"]]["file"]).exists())

    def service_properties(self, stack, name, filename):
        svc = stack["services"][name]
        ref = next(ref for ref in svc["configs"] if ref["target"] == "/etc/cluster/" + filename)
        return render.load_xml(stack["configs"][ref["source"]]["file"])

    def test_every_service_receives_xml_without_property_environments(self):
        stack = render.render(self.cfg, self.output)
        prefixes = ("CORE_CONF_", "HDFS_CONF_", "YARN_CONF_", "MAPRED_CONF_", "HIVE_SITE_CONF_")
        for name, svc in stack["services"].items():
            self.assertFalse(any(k.startswith(prefixes) for k in svc["environment"]))
            if name == "postgres":
                continue
            targets = [r["target"] for r in svc["configs"]]
            self.assertEqual(len(targets), len(set(targets)))
            for filename in ("core-site.xml", "hdfs-site.xml", "yarn-site.xml", "mapred-site.xml"):
                props = self.service_properties(stack, name, filename)
                self.assertTrue(props)
            if not name.startswith(("spark-", "hive-")):
                self.assertEqual(svc["entrypoint"], ["bash", "/opt/cluster/hadoop-entrypoint.sh"])
                self.assertIn("/opt/cluster/config-functions.sh", targets)
                self.assertIn("/opt/cluster/hadoop-entrypoint.sh", targets)

    def test_worker_identity_and_inventory_resources_are_in_xml(self):
        self.cfg["hdfs_replication"] = 1
        self.cfg["yarn_memory_mb"] = 6144
        self.cfg["yarn_vcores"] = 3
        stack = render.render(self.cfg, self.output)
        for worker in self.cfg["workers"]:
            dn, nm = "datanode-" + worker["id"], "nodemanager-" + worker["id"]
            hdfs = self.service_properties(stack, dn, "hdfs-site.xml")
            yarn = self.service_properties(stack, nm, "yarn-site.xml")
            self.assertEqual(hdfs["dfs.datanode.hostname"], dn)
            self.assertEqual(hdfs["dfs.replication"], "1")
            self.assertEqual(yarn["yarn.nodemanager.hostname"], nm)
            self.assertEqual(yarn["yarn.nodemanager.resource.memory-mb"], "6144")
            self.assertEqual(yarn["yarn.nodemanager.resource.cpu-vcores"], "3")
        master = self.service_properties(stack, "spark-master", "hdfs-site.xml")
        self.assertNotIn("dfs.datanode.hostname", master)

    def test_role_specific_hive_xml_has_no_password_in_clients(self):
        stack = render.render(self.cfg, self.output)
        for name in ("spark-master", "spark-worker-1", "hive-server"):
            props = self.service_properties(stack, name, "hive-site.xml")
            self.assertEqual(props["hive.metastore.uris"], "thrift://hive-metastore:9083")
            self.assertFalse(any("jdo" in key for key in props))
        metastore = self.service_properties(stack, "hive-metastore", "hive-site.xml")
        self.assertEqual(metastore["javax.jdo.option.ConnectionPassword"], "@@POSTGRES_PASSWORD@@")
        self.assertEqual(metastore["hive.metastore.schema.verification"], "true")

    def test_native_xml_metadata_survives_rendering(self):
        source = self.output / "source.xml"
        source.write_text('<configuration><!-- explanation -->'
                          '<property><name>x</name><value>1</value><description>setting</description>'
                          '<final>true</final></property></configuration>')
        result = render.xml({"x": "2", "y": "3"}, [source])
        tree = ET.fromstring(result)
        prop = next(p for p in tree.findall("property") if p.findtext("name") == "x")
        self.assertEqual(prop.findtext("value"), "2")
        self.assertEqual(prop.findtext("description"), "setting")
        self.assertEqual(prop.findtext("final"), "true")
        self.assertIn('<!-- explanation -->', result)

    def test_duplicate_xml_properties_are_rejected(self):
        path = self.output / "invalid.xml"
        path.write_text('<configuration><property><name>x</name><value>1</value></property>'
                        '<property><name>x</name><value>2</value></property></configuration>')
        with self.assertRaises(ValueError):
            render.load_xml(path)

    def test_invalid_topologies_rejected(self):
        invalid = []
        for key, value in (("workers", []), ("hdfs_replication", 3),
                           ("hdfs_replication", True), ("yarn_memory_mb", 1024),
                           ("stack", "../oops"), ("image_tag", "x;echo nope")):
            cfg = copy.deepcopy(self.cfg)
            cfg[key] = value
            invalid.append(cfg)
        for key in ("id", "node"):
            cfg = copy.deepcopy(self.cfg)
            cfg["workers"][1][key] = cfg["workers"][0][key]
            invalid.append(cfg)
        for cfg in invalid:
            with self.subTest(cfg=cfg), self.assertRaises(ValueError):
                self.inventory(cfg)


if __name__ == "__main__":
    unittest.main()
