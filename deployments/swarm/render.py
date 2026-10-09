#!/usr/bin/env python3
"""Render a Swarm stack with one stable service per worker (stdlib only)."""
import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
HADOOP_TAG = "2.0.0-hadoop3.2.1-java8"


def load_inventory(path):
    cfg = json.loads(Path(path).read_text())
    required = {"stack", "master_node", "workers", "image_prefix", "image_tag",
                "postgres_password_secret", "hdfs_replication", "yarn_memory_mb",
                "yarn_vcores", "spark_worker_memory", "spark_worker_cores"}
    if set(cfg) != required:
        raise ValueError(f"Inventory fields must be exactly: {sorted(required)}")
    name = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
    for key in ("stack", "master_node"):
        if not isinstance(cfg[key], str) or not name.fullmatch(cfg[key]):
            raise ValueError(f"Invalid {key}: use lowercase letters, digits and hyphens")
    if not isinstance(cfg["postgres_password_secret"], str) or not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", cfg["postgres_password_secret"]):
        raise ValueError("Invalid postgres_password_secret")
    workers = cfg["workers"]
    if not isinstance(workers, list) or not workers:
        raise ValueError("At least one worker is required")
    for w in workers:
        if not isinstance(w, dict) or set(w) != {"id", "node"}:
            raise ValueError("Each worker needs exactly id and node")
        if any(not isinstance(v, str) or not name.fullmatch(v) for v in w.values()):
            raise ValueError("Invalid worker id or node")
    for key in ("id", "node"):
        if len({w[key] for w in workers}) != len(workers):
            raise ValueError(f"Duplicate worker {key}")
    # Master and workers may share a host for a small learning cluster.
    for key in ("hdfs_replication", "yarn_memory_mb", "yarn_vcores", "spark_worker_cores"):
        if type(cfg[key]) is not int or cfg[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if cfg["hdfs_replication"] > len(workers):
        raise ValueError("hdfs_replication cannot exceed the number of workers")
    if cfg["yarn_memory_mb"] < 2048:
        raise ValueError("yarn_memory_mb must be at least 2048 for the default MR tasks")
    if not isinstance(cfg["spark_worker_memory"], str) or not re.fullmatch(
            r"[1-9][0-9]*[MG]", cfg["spark_worker_memory"]):
        raise ValueError("spark_worker_memory must look like 2048M or 2G")
    if not isinstance(cfg["image_prefix"], str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9./:_-]*", cfg["image_prefix"]):
        raise ValueError("Invalid image_prefix")
    if not isinstance(cfg["image_tag"], str) or not re.fullmatch(
            r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", cfg["image_tag"]):
        raise ValueError("Invalid image_tag")
    return cfg


def load_xml(path):
    tree = ET.parse(path).getroot()
    if tree.tag != "configuration":
        raise ValueError(f"Expected <configuration> in {path}")
    properties = {}
    for prop in tree.findall("property"):
        name, value = prop.findtext("name"), prop.findtext("value")
        if not name or value is None or name in properties:
            raise ValueError(f"Invalid or duplicate XML property in {path}: {name}")
        properties[name] = value
    return properties


def common_properties(cfg):
    properties = {filename: load_xml(REPO_ROOT / "config/hadoop" / filename)
                  for filename in ("core-site.xml", "hdfs-site.xml", "yarn-site.xml", "mapred-site.xml")}
    for filename in ("yarn-site.xml", "mapred-site.xml"):
        properties[filename].update(load_xml(ROOT / "overrides" / filename))
    properties["hdfs-site.xml"]["dfs.replication"] = str(cfg["hdfs_replication"])
    properties["yarn-site.xml"].update({
        "yarn.nodemanager.resource.memory-mb": str(cfg["yarn_memory_mb"]),
        "yarn.nodemanager.resource.cpu-vcores": str(cfg["yarn_vcores"]),
        "yarn.scheduler.maximum-allocation-mb": str(cfg["yarn_memory_mb"]),
        "yarn.scheduler.maximum-allocation-vcores": str(cfg["yarn_vcores"]),
        "yarn.scheduler.capacity.root.default.maximum-allocation-mb": str(cfg["yarn_memory_mb"]),
        "yarn.scheduler.capacity.root.default.maximum-allocation-vcores": str(cfg["yarn_vcores"]),
    })
    return properties


def xml_sources(filename):
    sources = [REPO_ROOT / "config/hadoop" / filename]
    override = ROOT / "overrides" / filename
    if override.exists():
        sources.append(override)
    return sources


def xml(properties, sources=()):
    tree = ET.Element("configuration")
    nodes = {}
    # Retain native XML metadata such as description/final and source comments.
    for source in sources:
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        for node in ET.parse(source, parser=parser).getroot():
            child = copy.deepcopy(node)
            if child.tag == "property":
                name = child.findtext("name")
                if name in nodes:
                    tree.remove(nodes[name])
                nodes[name] = child
            tree.append(child)
    for name, value in sorted(properties.items()):
        if name not in nodes:
            nodes[name] = ET.SubElement(tree, "property")
            ET.SubElement(nodes[name], "name").text = name
            ET.SubElement(nodes[name], "value")
        nodes[name].find("value").text = value
    ET.indent(tree)
    return ET.tostring(tree, encoding="unicode") + "\n"


def render(cfg, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    properties = common_properties(cfg)
    stack = {"version": "3.8", "services": {}, "volumes": {},
             "networks": {"cluster": {"driver": "overlay", "attachable": True}},
             "configs": {},
             "secrets": {"postgres_password": {"external": True,
                         "name": cfg["postgres_password_secret"]}}}

    def service(name, image, node, overrides=None, ports=(), volumes=(), command=None):
        svc = {"image": image, "hostname": name, "networks": ["cluster"],
               "environment": dict(overrides or {}),
               "deploy": {"replicas": 1, "endpoint_mode": "dnsrr",
                          "placement": {"constraints": [f"node.hostname == {node}"]},
                          "restart_policy": {"condition": "any", "delay": "5s"},
                          "update_config": {"parallelism": 1, "order": "stop-first"}}}
        if ports:
            svc["ports"] = [{"target": target, "published": published, "protocol": "tcp", "mode": "host"}
                            for target, published in ports]
        if volumes:
            svc["volumes"] = []
            for volume, target in volumes:
                stack["volumes"][volume] = {}
                svc["volumes"].append({"type": "volume", "source": volume, "target": target})
        if command:
            svc["command"] = command
        stack["services"][name] = svc
        return svc

    master = cfg["master_node"]
    def hadoop(role):
        return f"bde2020/hadoop-{role}:{HADOOP_TAG}"
    image = lambda role: f"{cfg['image_prefix']}/{role}:{cfg['image_tag']}"
    service("namenode", hadoop("namenode"), master, {"CLUSTER_NAME": cfg["stack"]},
            [(9870, 19870)], [("namenode", "/hadoop/dfs/name")], ["namenode"])
    wait_nn = "namenode:9000 namenode:9870"
    service("resourcemanager", hadoop("resourcemanager"), master,
            {"SERVICE_PRECONDITION": wait_nn}, [(8088, 18088)], command=["resourcemanager"])
    service("historyserver", hadoop("historyserver"), master,
            {"SERVICE_PRECONDITION": wait_nn + " resourcemanager:8088"},
            [(8188, 18188)], [("timeline", "/hadoop/yarn/timeline")], ["historyserver"])
    service("jobhistory", hadoop("resourcemanager"), master,
            {"SERVICE_PRECONDITION": wait_nn}, [(19888, 19888)],
            command=["jobhistory"])

    postgres = service("postgres", "postgres:15-alpine", master,
                       volumes=[("postgres", "/var/lib/postgresql/data")])
    postgres["environment"] = {"POSTGRES_USER": "hive", "POSTGRES_DB": "hive_metastore",
                               "POSTGRES_PASSWORD_FILE": "/run/secrets/postgres_password"}
    postgres["secrets"] = ["postgres_password"]
    postgres["healthcheck"] = {"test": ["CMD-SHELL", "pg_isready -U hive -d hive_metastore"],
                               "interval": "10s", "timeout": "5s", "retries": 10}
    metastore = service("hive-metastore", image("hive"), master,
                        {"SERVICE_PRECONDITION": wait_nn + " postgres:5432"}, command=["metastore"])
    metastore["secrets"] = ["postgres_password"]
    service("hive-server", image("hive"), master,
            {"SERVICE_PRECONDITION": wait_nn + " hive-metastore:9083"},
            [(10000, 20000), (10002, 20002)], command=["server"])
    service("spark-master", image("spark"), master, ports=[(8080, 18080)], command=["master"])

    for worker in cfg["workers"]:
        ident, node = worker["id"], worker["node"]
        dn, nm, sw = f"datanode-{ident}", f"nodemanager-{ident}", f"spark-{ident}"
        service(dn, hadoop("datanode"), node,
                {"SERVICE_PRECONDITION": wait_nn},
                [(9864, 19864)], [(dn, "/hadoop/dfs/data")], ["datanode"])
        service(nm, hadoop("nodemanager"), node,
                {"SERVICE_PRECONDITION": wait_nn + " resourcemanager:8088"}, [(8042, 18042)],
                [(nm, "/hadoop/yarn")], ["nodemanager"])
        service(sw, image("spark"), node,
                {"SPARK_WORKER_HOST": sw, "SPARK_WORKER_CORES": str(cfg["spark_worker_cores"]),
                 "SPARK_WORKER_MEMORY": cfg["spark_worker_memory"]},
                [(8081, 18081)], [(sw, "/spark/work")], ["worker"])

    # Every consumer gets complete XML files; no upstream env renderer runs.
    def config_ref(filename, content, target):
        path = output / filename
        path.write_text(content)
        key = filename.replace(".", "-") + "-" + hashlib.sha256(content.encode()).hexdigest()[:12]
        stack["configs"][key] = {"file": str(path)}
        return {"source": key, "target": target}

    common_refs = {filename: config_ref(filename, xml(values, xml_sources(filename)), f"/etc/cluster/{filename}")
                   for filename, values in properties.items()}
    scripts = [config_ref(filename, (REPO_ROOT / "images/common" / filename).read_text(),
                          f"/opt/cluster/{filename}")
               for filename in ("hadoop-entrypoint.sh", "config-functions.sh")]
    for role in ("client", "server", "metastore"):
        load_xml(REPO_ROOT / f"config/hive/{role}/hive-site.xml")
    hive_refs = {role: config_ref(f"hive-{role}-site.xml",
                                 (REPO_ROOT / f"config/hive/{role}/hive-site.xml").read_text(),
                                 "/etc/cluster/hive-site.xml")
                 for role in ("client", "server", "metastore")}
    # Keep the top-level client files for cluster.sh's temporary containers.
    (output / "hive-site.xml").write_text((REPO_ROOT / "config/hive/client/hive-site.xml").read_text())
    for name, svc in stack["services"].items():
        if name == "postgres":
            continue
        refs = dict(common_refs)
        if name.startswith("datanode-"):
            values = {**properties["hdfs-site.xml"], "dfs.datanode.hostname": name}
            refs["hdfs-site.xml"] = config_ref(f"{name}-hdfs-site.xml", xml(values, xml_sources("hdfs-site.xml")), "/etc/cluster/hdfs-site.xml")
        elif name.startswith("nodemanager-"):
            values = {**properties["yarn-site.xml"], "yarn.nodemanager.hostname": name}
            refs["yarn-site.xml"] = config_ref(f"{name}-yarn-site.xml", xml(values, xml_sources("yarn-site.xml")), "/etc/cluster/yarn-site.xml")
        svc["configs"] = list(refs.values())
        if name.startswith("spark-"):
            svc["configs"].append(hive_refs["client"])
        elif name in ("hive-metastore", "hive-server"):
            role = "metastore" if name == "hive-metastore" else "server"
            svc["configs"].append(hive_refs[role])
        else:
            svc["entrypoint"] = ["bash", "/opt/cluster/hadoop-entrypoint.sh"]
            svc["configs"].extend(scripts)
    (output / "stack.json").write_text(json.dumps(stack, indent=2) + "\n")
    return stack


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    try:
        render(load_inventory(args.inventory), args.output)
    except (ValueError, KeyError, TypeError, ET.ParseError) as exc:
        parser.error(str(exc))
    print(args.output.resolve() / "stack.json")
