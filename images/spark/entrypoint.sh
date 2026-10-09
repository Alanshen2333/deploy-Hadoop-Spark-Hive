#!/bin/bash
set -euo pipefail
export SPARK_HOME=/spark
export SPARK_CONF_DIR=/spark/conf
export HADOOP_CONF_DIR=/spark/conf

# shellcheck source=images/common/config-functions.sh
source "$(dirname "$0")/config-functions.sh"
prepare_hadoop_config
prepare_hive_config "$SPARK_CONF_DIR/hive-site.xml"
wait_for_dependencies
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
