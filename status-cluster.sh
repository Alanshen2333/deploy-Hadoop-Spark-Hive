#!/bin/bash
cd "$(dirname "$0")"

echo "======================================"
echo "  集群运行状态"
echo "======================================"
docker-compose ps

echo ""
echo "======================================"
echo "  HDFS 状态"
echo "======================================"
docker-compose exec namenode hdfs dfsadmin -report 2>&1 | head -10

echo ""
echo "======================================"
echo "  YARN 节点状态"
echo "======================================"
docker-compose exec resourcemanager yarn node -list 2>&1 | grep -E "Node-Id|State|RUNNING" | head -5
