import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
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
