#!/bin/bash
set -euo pipefail
export SPARK_HOME=/spark
export SPARK_CONF_DIR=/spark/conf
export HADOOP_CONF_DIR=/spark/conf

# Swarm supplies configs outside /spark/conf to avoid changing read-only mounts.
cp /etc/cluster/*.xml /spark/conf/
case "${1:-}" in
    master)
        exec /spark/bin/spark-class org.apache.spark.deploy.master.Master \
            --host spark-master --port 7077 --webui-port 8080
        ;;
    worker)
        : "${SPARK_WORKER_HOST:?Missing stable worker hostname}"
        exec /spark/bin/spark-class org.apache.spark.deploy.worker.Worker \
            --host "$SPARK_WORKER_HOST" --port 8881 --webui-port 8081 \
            --cores "${SPARK_WORKER_CORES:-2}" --memory "${SPARK_WORKER_MEMORY:-2G}" \
            spark://spark-master:7077
        ;;
    *) exec "$@" ;;
esac
