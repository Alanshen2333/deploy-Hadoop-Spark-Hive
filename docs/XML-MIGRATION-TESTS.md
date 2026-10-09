# XML 配置改造测试清单

记录日期：2026-10-09。适用分支：`codex/xml-config`。
本次变更包含部署目录重组，以及 Compose / Swarm 的 XML 配置与启动入口改造。
本文区分本地回归结果和真实服务验收；执行后请更新勾选项、结果与证据，避免旧状态引起误解。

## 已完成的检查

| 检查 | 本轮结果 | 范围 |
| --- | --- | --- |
| 本机回归测试 | 33 项全部通过 | XML 来源、配置交付、拓扑、启动失败与持久化保护等 |
| 已有 Linux 容器复验 | 32 项通过，1 项跳过 | 容器缺少 Compose 插件；该项已在本机通过 |
| Shell 语法 | 通过 | 部署及镜像启动脚本 |
| Compose 配置展开 | 通过 | 只读配置挂载、Secret、原默认项目及命名卷身份 |
| Swarm stack 配置展开 | 通过 | 完整 XML、节点 hostname、资源配额与 configs 引用 |
| 改造前后配置对比 | 通过 | Swarm 拓扑、镜像、端口、卷身份与原环境变量指定的 Hadoop 属性保留 |
| 文档链接、构建源文件路径、空白检查 | 通过 | 仓库内静态检查 |

以下事项尚未完成：真实 BDE 服务启动、派生镜像构建、ShellCheck、集群作业与多机验收。
本轮 BDE NameNode 和 ShellCheck 镜像拉取长时间无进展，已停止；不能据此声称真实服务验收通过。

## 测试前记录

- [ ] 记录提交号、主机架构、Docker / Compose 版本，以及 Swarm 各节点 hostname。
- [ ] 记录原 Compose 项目名、Swarm stack 名称、已有卷及测试数据；迁移后必须沿用原身份。
- [ ] 为已有 NameNode / PostgreSQL 数据准备可恢复备份；失败注入和首次格式化只使用独立测试目录或卷。
- [ ] 确认 PostgreSQL 密码文件或 Secret 与已有数据库密码一致。
- [ ] 为 Swarm 派生镜像使用新 `image_tag`，构建并推送至所有节点可访问的仓库。

所有命令从仓库根目录执行。下面的 Compose 示例使用默认项目名；自定义环境应替换为原项目名。
已有数据库卷不会因更换密码文件或 Secret 自动轮换密码。

## 1. CI、静态配置与镜像

- [ ] `Deployment validation` 的 validate job 通过，包括 ShellCheck。
- [ ] 完整本地回归通过，生成 XML 无重复属性，原生注释及 `description` / `final` 元信息保留。
- [ ] Compose 和 Swarm 配置展开成功，未再配置 `*_CONF_*` 属性变量或明文密码环境变量。
- [ ] Hive、Spark 镜像构建成功；仓库根目录构建上下文没有包含本地密码或生成目录。
- [ ] 如运行手动 CI smoke，记录该结果；单机 Swarm 成功不能替代真实多机网络验收。

```bash
python3 -m unittest discover -s tests -v
python3 deployments/swarm/render.py deployments/swarm/cluster.example.json
docker stack config -c deployments/swarm/build/stack.json
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml config
```

Swarm 构建前先配置本地 `deployments/swarm/cluster.json`：

```bash
./deployments/swarm/cluster.sh build
./deployments/swarm/cluster.sh push
```

## 2. Compose 真实启动与配置生效

- [ ] 新建测试环境能启动 NameNode、DataNode、YARN、Timeline、Spark、PostgreSQL 和 Hive。
- [ ] 各组件实际配置目录收到完整 XML，源文件仍为只读，无 BDE 转换流程产生的重复属性。
- [ ] Hadoop 的最终值来自 XML，NameNode / DataNode 数据目录及 Timeline 存储目录与卷挂载一致。
- [ ] HDFS / YARN / Spark 工作节点均注册，Web UI 和 HiveServer2 可访问。
- [ ] Hive 仅首次初始化空数据库；已有数据库验证 schema 后启动，不重复初始化。
- [ ] 单机 Hive 和 Spark 使用同一个数据库密码，`hive-site.xml` 密码占位符已被替换，文件权限为 0600，日志无密码。
- [ ] 在独立测试配置中改一个可验证属性并重新创建受影响容器，运行时值随 XML 改变。

```bash
./deployments/compose/start-cluster.sh
./deployments/compose/status-cluster.sh

docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml exec namenode hdfs getconf -confKey fs.defaultFS
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml exec namenode hdfs getconf -confKey dfs.namenode.name.dir
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml exec namenode hdfs dfsadmin -report
docker-compose -p deploy-hadoop-spark-hive -f deployments/compose/docker-compose.yml exec resourcemanager yarn node -list -all
```

预期默认文件系统为 `hdfs://namenode:9000`，NameNode 路径为 `file:///hadoop/dfs/name`。
请检查生成文件的权限和结构，避免将含密码的完整 XML 写入测试记录。

## 3. Compose 作业与已有数据迁移

- [ ] HDFS 写入、读取和删除测试文件成功。
- [ ] YARN 运行真实 MapReduce 作业成功，不仅是节点状态正常。
- [ ] Hive 建表、写入和查询测试数据成功。
- [ ] Spark 实际计算成功，并能查询 Hive 的共享 Metastore。
- [ ] 停止再启动后 HDFS 文件、Hive 表和 PostgreSQL 元数据保留。
- [ ] 从原环境切换到新入口后使用原项目名和原卷，NameNode 未再次格式化；已有数据可读取。

```bash
./deployments/compose/hive-cli.sh
./deployments/compose/spark-shell.sh
```

在 Spark Shell 中执行，确认实际计算和 Metastore 访问：

```scala
val session = org.apache.spark.sql.SparkSession.builder().enableHiveSupport().getOrCreate()
require(session.range(0, 1000, 1, 8).count() == 1000)
require(session.sql("SHOW DATABASES").count() > 0)
```

Hive 和 HDFS 的读写测试应使用单独命名的临时表与文件，完成后清理。

## 4. Swarm 多机部署与作业

- [ ] Hive / Spark 新镜像可被所有节点拉取，所有服务在规定 hostname 上启动。
- [ ] 每个 Hadoop / Hive / Spark 服务收到完整 XML；Hadoop 公共入口脚本通过 configs 正确加载。
- [ ] 每个 DataNode 的 `dfs.datanode.hostname`、NodeManager 的 `yarn.nodemanager.hostname` 与其稳定服务名称一致。
- [ ] 清单中的 HDFS 副本数、YARN 内存 / CPU 与调度上限在实际服务中生效。
- [ ] NameNode、DataNode、Timeline、YARN 及 Spark 工作目录使用预期持久卷。
- [ ] 仅 PostgreSQL / Hive Metastore 持有数据库 Secret；HiveServer2 和 Spark XML 不含 JDBC 密码。
- [ ] `smoke-test.sh` 整体通过：HDFS 跨节点写读、YARN MapReduce、HiveServer2 和分布式 Spark + Metastore 查询。
- [ ] 真实多机上完成同一验收，确认防火墙、overlay DNS、DataNode 连接及 Spark driver 回连。

```bash
./deployments/swarm/cluster.sh deploy
./deployments/swarm/cluster.sh status
./deployments/swarm/smoke-test.sh
```

验收成功应包含 `SWARM_SPARK_HIVE_OK` 及整体通过提示。报告默认位于
`deployments/swarm/build/hdfs-report.txt`、`yarn-report.txt` 和 `spark-smoke.txt`。
`deploy` 返回成功仅表示已提交部署任务。

## 5. Swarm 配置更新、重启与扩容

- [ ] 修改源 XML 后重新部署，内容版本名和服务引用更新，实际配置值改变。
- [ ] 修改节点清单中的资源配额或副本数后重新部署，相应 XML 正确更新。
- [ ] 修改公共 Hadoop 入口脚本后，configs 版本和引用更新；修改镜像入口后使用新 tag。
- [ ] 重启服务后原 NameNode / PostgreSQL / HDFS 数据仍可读取，未生成另一组空卷。
- [ ] 增加一台 worker 后只新增其工作服务及卷，原服务与卷身份保留，工作节点计数与清单一致。

## 6. 隔离环境中的失败保护

以下项目仅使用独立测试卷或临时配置，不修改现有集群的数据目录。

- [ ] NameNode 空目录首次格式化成功；同一目录重启时不格式化。
- [ ] NameNode 非空但缺少 `current/VERSION` 时拒绝格式化；非空 `lost+found` 内容保留。
- [ ] 缺少任一必需 XML 时服务不启动，并给出文件名。
- [ ] 依赖端口不可达时有限等待后失败，不提前启动服务。
- [ ] 缺失或空密码文件时 JDBC 角色失败；不需要密码的 HiveServer2 / Spark Client 正常使用自己的模板。
- [ ] 密码含 XML 特殊字符时正确转义，真实数据库仍能认证；密码未出现在日志中。
- [ ] Hive schema 初始化或验证失败时不启动 Metastore。

## 结果记录

完成测试后填写实际提交号和证据位置，并将上述状态更新为“通过 / 失败 / 未执行”。

| 场景 | 提交号 / 镜像 tag | 主机 / 拓扑 | 结果 | 日志或报告路径 | 问题与后续处理 |
| --- | --- | --- | --- | --- | --- |
| CI validate | 待填写 | 待填写 | 未执行 | 待填写 | 待填写 |
| Compose 新环境 | 待填写 | 待填写 | 未执行 | 待填写 | 待填写 |
| Compose 已有数据迁移 | 待填写 | 待填写 | 未执行 | 待填写 | 待填写 |
| 单机 Swarm smoke | 待填写 | 待填写 | 未执行 | 待填写 | 待填写 |
| 真实多机 Swarm | 待填写 | 待填写 | 未执行 | 待填写 | 待填写 |
| 配置更新 / 重启 / 扩容 | 待填写 | 待填写 | 未执行 | 待填写 | 待填写 |
| 失败保护 | 待填写 | 隔离环境 | 未执行 | 待填写 | 待填写 |
