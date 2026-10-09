#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
inventory=${CLUSTER_CONFIG:-./cluster.json}
expected=$(python3 - "$inventory" <<'PY'
import json, sys
print(len(json.load(open(sys.argv[1]))['workers']))
PY
)
./cluster.sh render >/dev/null
./cluster.sh hdfs dfsadmin -report > build/hdfs-report.txt
python3 - "$expected" build/hdfs-report.txt <<'PY'
import re, sys
report = open(sys.argv[2]).read()
match = re.search(r'Live datanodes \((\d+)\)', report)
if not match or int(match[1]) != int(sys.argv[1]):
    sys.exit('Unexpected number of live DataNodes:\n' + report)
print('All expected DataNodes are live.')
PY
./cluster.sh yarn node -list -all > build/yarn-report.txt
python3 - "$expected" build/yarn-report.txt <<'PY'
import sys
report = open(sys.argv[2]).read()
running = sum('RUNNING' in line.split() for line in report.splitlines())
if running != int(sys.argv[1]):
    sys.exit('Unexpected number of running NodeManagers:\n' + report)
print('All expected NodeManagers are running.')
PY
# A real HDFS write/read crosses the DataNode network, unlike dfsadmin -report.
path="/tmp/swarm-smoke-$$"
trap './cluster.sh hdfs dfs -rm -r -f "$path" >/dev/null 2>&1 || true' EXIT
printf 'swarm-hdfs-ok\n' | ./cluster.sh hdfs dfs -put - "$path"
[[ $(./cluster.sh hdfs dfs -cat "$path") == swarm-hdfs-ok ]]
./cluster.sh hive -e 'SHOW DATABASES;'
./cluster.sh hadoop jar /opt/hadoop-3.2.1/share/hadoop/mapreduce/hadoop-mapreduce-examples-3.2.1.jar pi 2 1000
# Spark-shell can return 0 for failed Scala statements. Require our success marker.
./cluster.sh spark-shell --conf spark.cores.max=2 --conf spark.executor.memory=1g --conf spark.swarm.expectedWorkers="$expected" <<'SCALA' | tee build/spark-smoke.txt
try {
  val source = scala.io.Source.fromURL("http://spark-master:8080/json/")
  val master = try { new com.fasterxml.jackson.databind.ObjectMapper().readTree(source.mkString) } finally { source.close() }
  val workers = master.get("workers").elements()
  var alive = 0
  while (workers.hasNext) { if (workers.next().get("state").asText() == "ALIVE") alive += 1 }
  require(alive == sc.getConf.getInt("spark.swarm.expectedWorkers", 0), "Unexpected number of Spark workers")
  val session = org.apache.spark.sql.SparkSession.builder().enableHiveSupport().getOrCreate()
  val result = session.range(0, 1000, 1, 8).count()
  require(result == 1000)
  require(session.sql("SHOW DATABASES").count() > 0)
  println("SWARM_SPARK_HIVE_OK")
} catch { case e: Throwable => e.printStackTrace(); System.exit(1) }
System.exit(0)
SCALA
grep -q '^SWARM_SPARK_HIVE_OK$' build/spark-smoke.txt
echo 'HDFS, YARN MapReduce, HiveServer2 and a distributed Spark job passed.'
