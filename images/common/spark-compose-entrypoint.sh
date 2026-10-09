#!/bin/bash
set -euo pipefail
# shellcheck source=images/common/config-functions.sh
source "$(dirname "$0")/config-functions.sh"
export SPARK_HOME=/spark
export SPARK_CONF_DIR=${SPARK_CONF_DIR:-/spark/conf}
export HADOOP_CONF_DIR=$SPARK_CONF_DIR
prepare_hadoop_config
prepare_hive_config "$SPARK_CONF_DIR/hive-site.xml"
wait_for_dependencies
# Retain the upstream Master/Worker command, without environment-to-XML rendering.
exec "$@"
