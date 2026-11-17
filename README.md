# 衡石 · 值班切主演练沙盘
衡石数据值班组（10人）把节点巡检、故障剧本与切主证明合并为可复核演练记录。

## 业务与模块
原流程用值班表记录节点、聊天传递故障、人工比较日志。痛点：输入版本混乱、隔离证明缺失、决策无法复查。上游是巡检记录；本工具替代人工纸上演练；下游是复核人和运维值班负责人。模块为节点状态、故障剧本、日志证明、演练队列、决策证据，配套登录及JSON导出。实体 Node / Scenario / ProofBatch / Drill 全链路实现。

**边界：受控教学/运维演练计算模型，不连接真实复制集群、不执行真实生产选主；任期、日志位置和fencing均由用户输入声明。** 本题真实 MySQL 保存业务输入/快照/结果，Python 实际计算规则，后台 worker 异步处理。

## 启动
```bash
cp .env.example .env
docker compose up -d --build
# http://localhost:18249
# API http://localhost:19249/docs
docker compose exec -T backend python -m scripts.seed_demo
docker compose down --remove-orphans
```
初次启动自动seed；脚本自然键查重，不覆盖用户修改。数据库初次连接和DDL失败会使启动失败，避免静默运行坏结构。演示seed异常的降级处理见测试报告。

|账号|密码|权限|典型动作|
|---|---|---|---|
|admin@hengshi.local|Drill2026!|全操作/审计/节点编辑|修改节点日志位置|
|operator@hengshi.local|Drill2026!|剧本新增/运行/导出|提交晚班演练|
|viewer@hengshi.local|Drill2026!|只读/导出|核对规则及结果|

## 一天剧本
09:00操作员登录；09:05核对hs-primary日志8100、hs-east日志8100、hs-west日志8098，任期均6；09:10创建shift-20261117剧本，允许损失0、新任期门槛7、主故障且已隔离；09:20提交晚班演练；09:25查看候选hs-east、新任期7、多数派2/2；09:30导出JSON；09:35运行“缺少隔离证明”案例，应阻断；09:40观察员复核但新增返回403；10:00管理员查看 /api/audits。

## 证明演练
10:05管理员把三个节点日志位置改为100（与演示链同尺度）；10:10在日志证明页为hs-primary录入100段链并声明提交点90（页面可生成演示分段）；10:15为hs-east提交同一链；10:20为hs-west先提交51–100段（乱序缺段，页面显示首个缺段1、暂存50段），再补1–50段接齐；10:25同键重试任一已落盘批次，返回已去重；10:30用不同内容覆盖hs-west位置95，整批409拒绝；10:35让hs-west在91–100使用不同内容（同位置异内容的分叉副本），状态页显示与原主在位置91分叉；10:40提交演练：提交点90在分叉之前，hs-west仍获准候选，hs-east按名称序胜出；10:45把提交点改为95重新演练，hs-west未覆盖已提交前缀被排除。

## 算法口径
输入为入队时冻结的节点、剧本与日志证明快照。法定票数 floor(配置投票节点数/2)+1；可达票扣除不可达/已隔离/本次故障主节点；候选必须可达、有投票权、非主、未隔离。新任期=max(节点任期)+1。所有安全条件成立时按有效日志位置降序、节点名升序确定候选；缺少旧主fencing、票数不足、未触发故障、任期不足或无合格候选均阻断。空节点、零投票节点、多个主节点计算失败并保存原因。结果含输入SHA256与模型版本，可重复计算。不会伪造真实集群共识证据。

### 日志证明
节点分段日志证明按批次接收：每段含位置、任期、内容、前序摘要，批次声明原主提交点及提交摘要；段摘要为 sha256(前序摘要|位置|任期|内容)，位置1锚定全零摘要。乱序或缺段的批次先暂存，链从位置1连续且前序摘要吻合的部分才可用，接齐后自动生效。同批任一冲突（批内或与已落盘段同位置异内容）整批拒绝；批次键幂等，写入中断后同键重试不重复收录。每落盘一批，证明版本号加一；证明接收与演练入队都串行于版本行锁，演练冻结同一完整版本，历史结论保留原依据。

声明提交点大于0时进入证明模式：候选的证明链必须覆盖原主已提交前缀（提交点处摘要与原主声明一致），日志位置相同的分叉副本只要分叉只在未提交尾部也获准切主；损失额度只用于未提交尾部，落后量按证明覆盖位置计算，巡检调高位置不算补证；无候选覆盖已提交前缀则阻断。未声明提交点时保持声明模式，按巡检声明位置评估（教学简化）。

## 工程
|组件|技术|
|---|---|
|前端|原生HTML/CSS/JS模块，Nginx1.27|
|后端|Python3.11/FastAPI/SQLAlchemy/PyJWT|
|任务|MySQL持久队列 + Redis worker互斥锁 + 心跳|
|存储|MySQL8.0、Redis7|
所有计算和权限检查在后端。JWT有效8小时，密码PBKDF2-SHA256 180000轮随机盐。20条待处理任务配额。审计保存业务写入动作；错误返回request-id。五服务均真实健康检查。

目录：frontend/src/api、stores、types、components/common、hooks、pages、router、utils、constants；backend/src/routes、controllers、services、models、schemas、middlewares、utils、constants、config；backend/scripts；backend/tests；backend/migrations。本地开发：安装backend/requirements.txt并设DATABASE_URL、REDIS_URL、JWT_SECRET，再运行uvicorn；前端以Nginx代理/api/去除前缀。后端测试：cd backend && python -m pytest tests/（使用临时SQLite，不依赖MySQL/Redis）。

环境：COMPOSE_PROJECT_NAME控制隔离命名；FRONTEND_PORT/BACKEND_PORT/DB_PORT为端口；DB_PASSWORD为演示数据库密码；JWT_SECRET为签名密钥；SEED_DEMO=false关闭演示数据。命名卷db-data、redis-data、artifacts；reset时显式down -v删除数据。前端字体依赖Google Fonts，离线回退serif/sans-serif。模型是简化安全门禁，非完整Raft实现。MIT许可。

枚举：角色在backend/src/constants/enums.py和frontend/src/constants/enums.js；任务状态同处定义，使用于models/entities.py、services/drill_service.py、worker.py、components/common/status.js；节点角色在schemas/node.py、pages/nodes.js；证明批次与分段在schemas/proof.py、services/proof_service.py、pages/proofs.js。测试、截图与已知差异见批次test-artifacts/gb-4110/TESTING.md。
