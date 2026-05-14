#!/bin/bash
cd "$(dirname "$0")"
docker-compose exec hive-server beeline -u jdbc:hive2://localhost:10000 -n "" -p ""
