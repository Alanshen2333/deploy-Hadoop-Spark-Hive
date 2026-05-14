# Dockerized Hadoop + Spark + Hive

基于 Docker Compose 的伪分布式大数据集群，一键启动 Hadoop、Spark 和 Hive 学习环境。

本项目最初通过 Docker 容器化部署大数据组件，后续进行了 **Git 规范化、配置标准化和文档完善**。

---

## 本次工作摘要

### 1. Git 仓库初始化与托管
- 初始化 Git 仓库并推送到 GitHub（`Alanshen2333/deploy-Hadoop-Spark-Hive`）
- 配置 `.gitignore`，排除运行时数据、日志、环境变量及 IDE 文件
- 保留 `data/` 和 `logs/` 目录结构（使用 `.gitkeep`）

### 2. 许可证
- 添加 **MIT License**

### 3. 端口配置标准化
- 提取所有端口定义为 `config.sh` 统一配置
- `start-cluster.sh` 的 Web UI / 服务提示信息改为读取变量，并修正为**宿主机映射端口**
- `hive-cli.sh`、`spark-shell.sh` 连接地址改为读取变量
- 消除了脚本中的硬编码端口，修改端口只需调整 `config.sh`

---

## 环境要求

- Docker >= 20.10
- Docker Compose >= 1.29

---

## 快速开始

### 1. 启动集群

```bash
./start-cluster.sh
```

脚本会自动完成：
- 拉取镜像并启动容器
- 等待服务初始化
- 创建 HDFS 基础目录并设置权限

### 2. 查看状态

```bash
./status-cluster.sh
```

### 3. 停止集群

```bash
./stop-cluster.sh
```

---

## Web UI 访问地址

| 服务 | 地址 |
|------|------|
| HDFS NameNode | http://localhost:19870 |
| YARN ResourceManager | http://localhost:18088 |
| Spark Master | http://localhost:18080 |
| Spark Worker | http://localhost:18081 |
| MapReduce History | http://localhost:18188 |
| Hive Web UI | http://localhost:20002 |

---

## 常用命令

### Hive CLI

```bash
./hive-cli.sh
```

### Spark Shell

```bash
./spark-shell.sh
```

---

## 端口映射

| 服务 | 容器端口 | 宿主机端口 |
|------|----------|-----------|
| HDFS NameNode RPC | 9000 | 19000 |
| HDFS NameNode Web | 9870 | 19870 |
| YARN ResourceManager | 8088 | 18088 |
| YARN NodeManager | 8042 | 18042 |
| MapReduce History | 8188 | 18188 |
| Spark Master | 8080 / 7077 | 18080 / 17077 |
| Spark Worker | 8081 | 18081 |
| HiveServer2 | 10000 | 20000 |
| Hive Web UI | 10002 | 20002 |

---

## 项目结构

```
.
├── docker-compose.yml      # 服务编排配置
├── hadoop.env              # Hadoop 环境变量
├── config.sh               # 端口统一配置（新增）
├── start-cluster.sh        # 启动集群（端口变量化）
├── stop-cluster.sh         # 停止集群
├── status-cluster.sh       # 查看状态
├── hive-cli.sh             # 进入 Hive CLI（端口变量化）
├── spark-shell.sh          # 进入 Spark Shell（端口变量化）
├── data/                   # 数据持久化目录（运行时生成，已忽略）
├── logs/                   # 日志目录（运行时生成，已忽略）
├── LICENSE                 # MIT 许可证（新增）
└── README.md               # 项目说明（新增）
```

---

## 技术栈

- **Hadoop** 3.2.1 (HDFS / YARN / MapReduce)
- **Spark** 3.3.0
- **Hive** 2.3.2 (内置 Derby 元数据库)

---

## License

[MIT](LICENSE)
