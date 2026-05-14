#!/bin/bash
cd "$(dirname "$0")"
source ./config.sh
docker-compose exec -it spark-master /spark/bin/spark-shell --master spark://spark-master:${CONTAINER_SPARK_MASTER_PORT}
