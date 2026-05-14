#!/bin/bash
cd "$(dirname "$0")"
docker-compose exec -it spark-master /spark/bin/spark-shell --master spark://spark-master:7077
