#!/bin/bash
set -euo pipefail
if [[ $1 == metastore ]]; then
    # Exactly one metastore task initializes the DB. Never hide initialization errors.
    if ! schematool -dbType postgres -info; then
        schematool -dbType postgres -initSchema
    fi
    schematool -dbType postgres -validate
    # NameNode's RPC port can open before safe mode ends and DataNodes register.
    ready=false
    for ((attempt=1; attempt<=120; attempt++)); do
        if hdfs dfs -mkdir -p /tmp /user/hive/warehouse \
            && hdfs dfs -chmod 1777 /tmp \
            && hdfs dfs -chmod 777 /user/hive/warehouse; then
            ready=true
            break
        fi
        sleep 5
    done
    $ready || { echo 'HDFS initialization timed out' >&2; exit 1; }
    exec hive --service metastore -p 9083
fi
exec hiveserver2
