# G4-T03 状态、持久记录与日志并发验收

日期：2026-09-19，Asia/Shanghai。**T03 已完成，T04 可执行。** 状态、持久记录及两模式在线只读日志消费通过；本卡不代表 Web 接口、自动恢复或本轮完整任务通过。

## 实现与证据边界

`src/sim_bridge/state.py` 提供与 Web 框架无关的确定性状态归约：实体配置／状态、三类搜索任务、完整规划航线、当前命令、区域和仿真时钟。标识、仿真毫秒和日志分片／行号保持十进制字符串。当前命令以实体及命令类别区分，避免两个实体相同 CommandID 相互覆盖；收到命令、状态确认执行、后端 TaskComplete 分开保存。完成不删除任务，过期不删除实体；合法 Remove 消息明确删除相关对象，墓碑阻止旧消息复活对象。G4 固定运行不复用已删除的业务身份，再次使用需新运行；重置分段归 G6。

`journal.py` 仅消费绑定当前运行的 UxAS 日志目录，以数据库分片和连续行号排序，128 行为读取批次。每批先结束只读事务，再进行 XML／LMCP 预检、持久化及状态处理。目录、文件身份、首条内容、运行清单、分片连续性、行号和已消费边界均有检查。XML 允许 C++ 省略空可选对象；缺必填、重复字段、未知字段／枚举、实体声明、非有限数字和越界坐标均拒绝。

独立规范化数据库保存事件及内容摘要，重复事件必须内容相同；不同运行和篡改记录拒绝。状态集合及删除墓碑各有上限，命令／航线仅保存每实体当前内容；全历史保留磁盘。TCP 原始捕获沿用 T02，日志 XML 重序列化仅用于语义核对，不宣称填回 TCP 缺失字节。

首轮历史验收重放 G3-T07 Headless 的 6834 条记录，TaskComplete 对应任务 1000／实体 400／740709 仿真毫秒；原场景中的 500 未被分配搜索航线。源日志重读与规范化记录重放快照一致，摘要为 `bd03238d841deaa08ea55c4f0a7a8bf98b583259ad46478dbce861eb75bf2234`。点／区域模型测试是生成消息夹具，实际三类执行归 T07。

## 已重现的日志缺陷与必要修复

首次在线运行 `g4-t03-test-20260919-232115-864` 中，后端正常规划和退出，但 UxAS stdout 明确记录 `database is locked`；数据库漏掉 SessionStatus 和 LineSearchTask。旧 DatabaseLoggerHelper 使用默认 rollback journal 且无等待，只读查询也可能使提交失败，异常路径还错误返回成功。该运行保持 failed。

隔离最小复现固定一个读事务：DELETE 模式写入失败；WAL 模式写入成功、旧读快照稳定、结束事务后看到新提交；读端写操作始终拒绝。正式 C++ 修复由唯一写端开启并核对 WAL，设置 5000ms 有限等待，插入异常返回 false。网关不写后端库，不执行 checkpoint；保留短读事务，运行限定本机文件系统。并行读写及 WAL 文件要求见 [SQLite WAL](https://sqlite.org/wal.html)，等待上限见 [SQLite busy timeout](https://sqlite.org/c3ref/busy_timeout.html)。

首次修复构建 `g2-t05-build-20260919-232403-798` 因旧 SQLiteCpp 不提供 getString() 而失败；按当前固定头文件改用 getText()。新候选已通过双路径验收、HelloWorld、发布矩阵和正式发布。AMASE、MDM、生成库、任务算法和原场景保持；G3 handoff 与旧收据不改写，G4 使用 config/g4-baseline.json 独立来源修订关联新包和 12 份 passed 收据。构建结果仍按既有约定为 candidate，不冒记成验收通过。

| 环节 | 当前合格编号 |
| --- | --- |
| UxAS 构建／候选验收 | g2-t05-build-20260919-232557-986／g2-t05-test-20260919-232811-379 |
| HelloWorld | g2-t06-test-20260919-233042-631 |
| 发布复验／正式发布 | g2-t07-test-20260919-233237-819／g2-t07-publish-20260919-233516-550 |
| 新输入资格 | g3-t01-check-20260919-233710-372 |
| Web 环境／入口复验 | g4-t01-checks-20260919-233824（含 verify 子运行） |
| T03 最终两模式 | g4-t03-test-20260919-233834-574 |

最终 result／entry-result passed，30 项来源在运行前后相同；32 项状态／记录检查、7 项新来源修订拒绝、两组日志锁复现及 T02 严格协议／队列回归通过。两模式各在线读取 54 批，最终日志各 101 行、实际 journal_mode=wal；7 个关键语义载荷摘要逐项与真实 TCP 对应，没有日志插入错误。每模式在线快照与本次持久事件重建逐字典一致；两个不同运行的时间和来源不同，不要求互相拥有同一摘要。

AMASE／UxAS 在两个模式均退出 0，无强制终止，接收线程结束且全部所属端口释放。中文路径构建／HelloWorld、T01 中文工作目录复验通过；独立 Web 服务的路径、退出和恢复仍归后续任务。最终在线证据只覆盖启动至真实规划取样；6834 条历史完成重建与本轮实际全程必须区分。

## 运行入口

以下独立入口已通过，工作目录为仓库根目录：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g4-state.tests.ps1 -PythonExecutable $pythonExe
# 单模式取样；默认重新检查正式输入资格。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g4-state.ps1 -PythonExecutable $pythonExe -Mode Headless
```

入口复用 G3 启动屏障和 T02 独立捕获，在后端写入期间反复只读消费日志，正常退出后对照关键 TCP 载荷与数据库语义，并从规范化持久记录重建快照。记录包含 journal-binding.json、normalized-events.db3、journal-boundaries.json、snapshot.json 和 state-evidence.json。GUI 短程自动关闭，不代替 T09 人工确认。
