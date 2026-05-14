#!/bin/bash
set -e

echo "======================================"
echo "  Hadoop + Spark + Hive 集群启动脚本"
echo "======================================"

# 确保在脚本所在目录运行
cd "$(dirname "$0")"

# 检查代理（如果设置了环境变量则使用）
if [ -n "$HTTP_PROXY" ] || [ -n "$http_proxy" ]; then
    echo "检测到代理设置，将用于 Docker 操作"
fi

echo ""
echo "[1/3] 启动 Docker 容器..."
docker-compose up -d

echo ""
echo "[2/3] 等待服务初始化（约 30 秒）..."
sleep 30

echo ""
echo "[3/3] 初始化 HDFS 目录..."
docker-compose exec namenode hdfs dfs -mkdir -p /tmp /user/hive/warehouse 2>/dev/null || true
docker-compose exec namenode hdfs dfs -chmod 777 /tmp /user/hive/warehouse 2>/dev/null || true

echo ""
echo "======================================"
echo "  集群启动完成！"
echo "======================================"
echo ""
echo "Web UI 访问地址："
echo "  HDFS NameNode:     http://localhost:9870"
echo "  YARN ResourceManager: http://localhost:8088"
echo "  Spark Master:      http://localhost:8080"
echo "  Spark Worker:      http://localhost:8081"
echo "  MapReduce History: http://localhost:8188"
echo ""
echo "服务端口："
echo "  HiveServer2:       localhost:10000 (beeline/jdbc)"
echo "  Hive Web UI:       localhost:10002"
echo "  HDFS:              localhost:9000"
echo "  Spark Master:      localhost:7077"
echo ""
echo "常用命令："
echo "  ./hive-cli.sh       进入 Hive CLI"
echo "  ./spark-shell.sh    进入 Spark Shell"
echo "  ./stop-cluster.sh   停止集群"
echo ""
