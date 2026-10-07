#!/usr/bin/env python3
"""Render a Swarm stack with one stable service per worker (stdlib only)."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
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


def common_env(cfg):
    env = dict(line.split("=", 1) for line in (ROOT.parent / "hadoop.env").read_text().splitlines()
               if line.strip() and not line.startswith("#"))
    env.update({
        "MULTIHOMED_NETWORK": "1",
        "HDFS_CONF_dfs_replication": str(cfg["hdfs_replication"]),
        "YARN_CONF_yarn_nodemanager_resource_memory___mb": str(cfg["yarn_memory_mb"]),
        "YARN_CONF_yarn_nodemanager_resource_cpu___vcores": str(cfg["yarn_vcores"]),
        "YARN_CONF_yarn_nodemanager_local___dirs": "/hadoop/yarn/local",
        "YARN_CONF_yarn_nodemanager_log___dirs": "/hadoop/yarn/logs",
        "YARN_CONF_yarn_scheduler_minimum___allocation___mb": "512",
        "YARN_CONF_yarn_scheduler_maximum___allocation___mb": str(cfg["yarn_memory_mb"]),
        "YARN_CONF_yarn_scheduler_maximum___allocation___vcores": str(cfg["yarn_vcores"]),
        "YARN_CONF_yarn_scheduler_capacity_root_default_maximum___allocation___mb": str(cfg["yarn_memory_mb"]),
        "YARN_CONF_yarn_scheduler_capacity_root_default_maximum___allocation___vcores": str(cfg["yarn_vcores"]),
        "MAPRED_CONF_mapred_child_java_opts": "-Xmx768m",
        "MAPRED_CONF_mapreduce_map_memory_mb": "1024",
        "MAPRED_CONF_mapreduce_reduce_memory_mb": "1024",
        "MAPRED_CONF_mapreduce_map_java_opts": "-Xmx768m",
        "MAPRED_CONF_mapreduce_reduce_java_opts": "-Xmx768m",
        "MAPRED_CONF_mapreduce_jobhistory_address": "jobhistory:10020",
        "MAPRED_CONF_mapreduce_jobhistory_webapp_address": "jobhistory:19888",
    })
    return env


def xml(properties):
    tree = ET.Element("configuration")
    for name, value in sorted(properties.items()):
        prop = ET.SubElement(tree, "property")
        ET.SubElement(prop, "name").text = name
        ET.SubElement(prop, "value").text = value
    ET.indent(tree)
    return ET.tostring(tree, encoding="unicode") + "\n"


def xml_properties(env, prefix):
    return {key[len(prefix) + 1:].replace("___", "-").replace("__", "@").replace("_", ".").replace("@", "_"): value
            for key, value in env.items() if key.startswith(prefix + "_")}


def render(cfg, output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = common_env(cfg)
    stack = {"version": "3.8", "services": {}, "volumes": {},
             "networks": {"cluster": {"driver": "overlay", "attachable": True}},
             "configs": {},
             "secrets": {"postgres_password": {"external": True,
                         "name": cfg["postgres_password_secret"]}}}

    def service(name, image, node, overrides=None, ports=(), volumes=(), command=None):
        svc = {"image": image, "hostname": name, "networks": ["cluster"],
               "environment": {**env, **(overrides or {})},
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
            [(9870, 19870)], [("namenode", "/hadoop/dfs/name")])
    wait_nn = "namenode:9000 namenode:9870"
    service("resourcemanager", hadoop("resourcemanager"), master,
            {"SERVICE_PRECONDITION": wait_nn}, [(8088, 18088)])
    service("historyserver", hadoop("historyserver"), master,
            {"SERVICE_PRECONDITION": wait_nn + " resourcemanager:8088"},
            [(8188, 18188)], [("timeline", "/hadoop/yarn/timeline")])
    service("jobhistory", hadoop("resourcemanager"), master,
            {"SERVICE_PRECONDITION": wait_nn}, [(19888, 19888)],
            command=["/opt/hadoop-3.2.1/bin/mapred", "historyserver"])

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
                {"SERVICE_PRECONDITION": wait_nn, "HDFS_CONF_dfs_datanode_hostname": dn},
                [(9864, 19864)], [(dn, "/hadoop/dfs/data")])
        service(nm, hadoop("nodemanager"), node,
                {"SERVICE_PRECONDITION": wait_nn + " resourcemanager:8088",
                 "YARN_CONF_yarn_nodemanager_hostname": nm}, [(8042, 18042)],
                [(nm, "/hadoop/yarn")])
        service(sw, image("spark"), node,
                {"SPARK_WORKER_HOST": sw, "SPARK_WORKER_CORES": str(cfg["spark_worker_cores"]),
                 "SPARK_WORKER_MEMORY": cfg["spark_worker_memory"]},
                [(8081, 18081)], [(sw, "/spark/work")], ["worker"])

    # Config names incorporate their content; Swarm configs are immutable.
    properties = {filename: xml_properties(env, prefix) for filename, prefix in
                  [("core-site.xml", "CORE_CONF"), ("hdfs-site.xml", "HDFS_CONF"),
                   ("yarn-site.xml", "YARN_CONF"), ("mapred-site.xml", "MAPRED_CONF")]}
    properties["hdfs-site.xml"].update({"dfs.client.use.datanode.hostname": "true",
                                       "dfs.datanode.use.datanode.hostname": "true"})
    properties["hive-site.xml"] = {"hive.metastore.uris": "thrift://hive-metastore:9083",
                                   "hive.metastore.warehouse.dir": "/user/hive/warehouse",
                                   "hive.metastore.schema.verification": "true"}
    spark_configs = []
    for filename, values in properties.items():
        content = xml(values)
        path = output / filename
        path.write_text(content)
        key = filename.replace(".", "-") + "-" + hashlib.sha256(content.encode()).hexdigest()[:12]
        stack["configs"][key] = {"file": str(path)}
        spark_configs.append({"source": key, "target": f"/etc/cluster/{filename}"})
    for name, svc in stack["services"].items():
        if name.startswith("spark-"):
            svc["configs"] = spark_configs
    (output / "stack.json").write_text(json.dumps(stack, indent=2) + "\n")
    return stack


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "build")
    args = parser.parse_args()
    try:
        render(load_inventory(args.inventory), args.output)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(args.output.resolve() / "stack.json")
