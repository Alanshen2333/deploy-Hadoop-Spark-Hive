#!/bin/bash

# =============================================================================
# 集群端口配置
# =============================================================================

# --- 宿主机暴露端口（Web UI / 客户端从宿主机访问用） ---
export HOST_HDFS_NAMENODE_WEB_PORT=19870
export HOST_HDFS_RPC_PORT=19000
export HOST_YARN_RM_PORT=18088
export HOST_YARN_NM_PORT=18042
export HOST_MR_HISTORY_PORT=18188
export HOST_SPARK_MASTER_WEB_PORT=18080
export HOST_SPARK_MASTER_PORT=17077
export HOST_SPARK_WORKER_PORT=18081
export HOST_HIVE_SERVER_PORT=20000
export HOST_HIVE_WEB_PORT=20002

# --- 容器内部端口（docker-compose exec 进入容器后使用） ---
export CONTAINER_HDFS_NAMENODE_WEB_PORT=9870
export CONTAINER_HDFS_RPC_PORT=9000
export CONTAINER_YARN_RM_PORT=8088
export CONTAINER_YARN_NM_PORT=8042
export CONTAINER_MR_HISTORY_PORT=8188
export CONTAINER_SPARK_MASTER_WEB_PORT=8080
export CONTAINER_SPARK_MASTER_PORT=7077
export CONTAINER_SPARK_WORKER_PORT=8081
export CONTAINER_HIVE_SERVER_PORT=10000
export CONTAINER_HIVE_WEB_PORT=10002
