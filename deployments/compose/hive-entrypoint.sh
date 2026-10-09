#!/bin/bash
set -euo pipefail
# shellcheck source=images/common/config-functions.sh
source /opt/cluster/config-functions.sh
prepare_hadoop_config
prepare_hive_config /opt/hive/conf/hive-site.xml
wait_for_dependencies
if ! schematool -dbType postgres -info; then
    schematool -dbType postgres -initSchema
fi
schematool -dbType postgres -validate
# Preserve the upstream HDFS setup and HiveServer2 startup behavior.
exec startup.sh
