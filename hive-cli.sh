#!/bin/bash
cd "$(dirname "$0")"
source ./config.sh
docker-compose exec hive-server beeline -u jdbc:hive2://localhost:${CONTAINER_HIVE_SERVER_PORT} -n "" -p ""
