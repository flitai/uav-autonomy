# G3-T03：受控启动与初始化验收

日期：2026-09-19，Asia/Shanghai。**G3-T03 已完成，T04 可执行、尚未启动；G3 阶段尚未完成。** 两模式真实初始化、故障矩阵与独立 GUI 正常收尾均通过。

## 1. 范围与入口

本卡建立 Windows 原生 AMASE／UxAS 的暂停启动、连接就绪、真实初始数据屏障、单次任务／请求和正常关闭。复用 T02 正式产物及同批七模型，不改变原示例、算法、生成代码或 G1／G2 入口。覆盖率不设数值门槛；本卡不验收覆盖计算、完整任务或规划命令实际执行。

- [运行编排](../scripts/g3_integration/runtime.py)、[初始化屏障](../scripts/g3_integration/gates.py)、[独立 AMASE 插件](../scripts/g3_integration/StartupProbe.java)。插件在本次 out/build 下编译，额外加入明确类路径，不替换正式 JAR。
- [默认配置](../config/g3-startup.json)：GUI 5555／9400／9500、无界面 5556／19400／19500、观察口 9999；两模式顺序运行。
- [运行入口](../scripts/windows/run-g3.ps1)、[自动验收入口](../tests/windows/g3-startup.tests.ps1)、[GUI 收尾入口](../scripts/windows/finish-g3-gui.ps1)。本版本 scope=startup，取得非空规划响应即正常收尾，不将短程启动运行解释为完整搜索。

以下从仓库根目录运行，Python 路径须指向已核查的 3.14.7 x64。脚本以自身位置解析仓库，可以从其他工作目录用绝对脚本路径调用。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
# 默认先进行新的只读资格复查；失败不会启动应用。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3.ps1 -PythonExecutable $pythonExe -Mode Headless
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-startup.tests.ps1 -PythonExecutable $pythonExe
# 可选：取得规划响应后暂停 GUI，保留本次控制进程，供观察。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3.ps1 -PythonExecutable $pythonExe -Mode Gui -KeepGui
# 在另一终端，用本次尚在运行的编号正常收尾。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\finish-g3-gui.ps1 -PythonExecutable $pythonExe -RunId '<G3_RUN_ID>'
```

运行／验收支持 `-Configuration`、`-RunId`；编号必须以 g3-t03- 开头，已有目录拒绝覆盖。可显式传入本轮合格 `-BaselineRunId`，仍复查冻结输入、正式包和消息库来源；省略时重新检查工具／CRT／完整交接资格。GUI 收尾核对运行状态和控制进程身份，仅发送本次本地关闭请求并等待最终收据，不结束其他进程。收尾本身不代表人工 GUI 验收，不借用 T02 的确认作为 G3-T07 确认。

## 2. 受控顺序与消息来源

1. 校验正式包、来源和配置；预检全部四个端口。原场景复制到独立目录，保留 785 秒时长、任务 1000 和 90 个水道点。
2. AMASE 初始化暂停。运行副本移除无界面 ConstructiveControl；插件记录实际加载的 AMASE／LMCP 来源及仿真时间。
3. 建立 AMASE 主链路、被动 Java 取样连接及 UxAS 观察连接。用 AMASE 真正收到的 KeyValuePair 探测、UxAS 原有 OnboardStatusReport 和 TCP/PID 检查区分监听、连接和可解析；轮询间隔不是固定启动延时。
4. 插件收到本次 request-start 后调用 SimTimer，以 1 倍速启动。观察口必须取得两实体配置，且每架至少五条不同时间、时间不回退、位置有变化的真实状态。状态／配置原始 LMCP 摘要与独立 AMASE TCP 取样一致，来源仍为 0／0。没有静态实体 XML 补齐。
5. 通过观察口仅注入一次原任务；等待任务 1000 的 TaskInitialized 和 AMASE 收到相同任务后，仅注入一次原 AutomationRequest。保留实际 UniqueAutomationRequest／Response ID、非空规划响应和命令清单；本卡不判定它们已经驱动任务航段。
6. 正常发送 KillService(-1)，本地插件调用应用的 requestShutdown。正常例要求两端退出 0、无强杀、接收尾部为空、端口释放；失败例保留失败状态及清理结果。

初始化整体、任务初始化、规划等待、关闭分别限 30 墙钟秒，资格检查后的独立运行器上限 2700 秒，其中预留 50 秒供 30 秒关闭等待、失败时回收和证据收尾；运行／GUI 等待到 2650 秒即失败并进入清理。GUI 保留观察仍受上限约束；超时失败，不能把故障清理当作正常通过。仿真时间、消息源时间与墙钟分开记录；实体／任务／命令／请求标识按字符串保存。

| 通道 | 设置与实测依据 |
| --- | --- |
| AMASE → UxAS 主桥 | ConsiderSelfGenerated=false，保留真实状态来源；ExportOnlyLocalMessages=true，避免将原巡航命令回送 |
| 验收控制输入 → UxAS | 客户端显式声明 G3Controller／900／1；观察桥 ConsiderSelfGenerated=true，将少量本地编排输入登记为 TcpBridge／100／观察桥服务 ID |
| UxAS → AMASE | 主桥导出本地规划命令、任务和就绪探测；任务输入由观察桥登记为本地来源后可到达 AMASE |
| UxAS → 观察客户端 | 订阅 afrl.／uxas.，接收器不回送任何收到的业务消息。桥会过滤自身导入的消息，因此不能要求注入消息在同一观察连接原样回显 |
| 控制输入的独立见证 | 使用原有 MessageLoggerDataService 的 SQLite 日志核对任务／请求各一次、来源改写及内容；任务原始字节另与 AMASE 取样和内部事件交叉核对 |

运行副本删除整个 SendMessagesService、PUB／PULL 桥和未使用实体的 TCP 配置，保留原规划服务与航点分段参数。全部差异写入 configuration.diff。独立编排没有转发接收消息，不用 PUB 来源过滤推断完整状态。

## 3. 验收证据

最终自动矩阵 `g3-t03-test-20260919-113944-818` 从仓库外的 E 盘根目录调用，result／entry-result 均 passed，11 组真实运行／故障与 10 项消息回放反例通过。前置资格为 `g3-t01-check-20260919-113233-558`；正式 AMASE、UxAS 与七模型沿用 [T02 正式批次](g3-protocol-validation.md)，43 项冻结输入不变，无须重建或重新发布正式二进制。

| 子运行 | 实测结果 |
| --- | --- |
| headless／gui／中文 空格运行 | 三组均通过；屏障时实体 400／500 分别已有 6／5 条真实状态，配置齐全且位置变化；两端退出 0 |
| 原任务与规划 | 任务、请求各一次；Unique 请求／响应均为字符串 ID 48，实际响应分配实体 400、命令 1、74 个航点；只登记规划收据 |
| 缺配置／静止状态 | 初始化整体达到 30 秒后明确失败，任务／请求均未发，两端正常关闭 |
| 提前请求 | 在真实连接已就绪但初始数据未齐时调用请求入口，被屏障拒绝，未写入网络 |
| 缺少任务初始化 | 仅故障副本移除 TaskManagerService，任务已发、请求未发，等待 30 秒失败后正常关闭 |
| 规划等待超时 | 仅故障副本移除 PlanBuilderService，并把 UxAS 自身等待设为 60 秒，使编排器的 30 秒上限先触发；失败后正常关闭 |
| 空规划响应 | 移除 PlanBuilderService、保留 UxAS 原有 5 秒等待，实际空响应被立即拒绝，不作为规划成功 |
| 关闭超时 | 故障插件忽略关闭请求；UxAS 正常退出，30 秒后仅终止本次 AMASE，子收据保持 failed 并记录连接断开 |
| 端口冲突 | 预占 5556，未启动任何应用或发送任务；占用监听仍可连接，验证没有结束其他实例 |

正常短程仿真约 4.47～4.53 秒；场景上限仍为原 785 秒。短程长度由屏障与实际响应决定，没有固定“运行若干秒即通过”的条件。三组均保留原两条 CommandID=100 巡航命令各一次；不能将巡航运动作为规划执行证据。

每个子运行保存原始字节、增量解码、AMASE 内部 XML 事件、UxAS 日志／数据库、注入记录、状态迁移、配置差异、类加载来源、PID／退出码及文件摘要。父收据绑定基线与编排来源，entry-result 记录环境、工作目录及持久 PATH 恢复。已有运行编号和缺失 Python 的入口反例均拒绝，历史成功收据摘要未变。

故障子收据保持 failed，矩阵通过只表示其预期失败和清理行为得到验证。另以本轮真实消息回放验证缺配置但两实体状态齐全、静态位置／时间、错误来源／任务及重复触发，10 项回放修改明确标注为内存反例，不作为真实运行证据。完整矩阵首轮 `g3-t03-test-20260919-112311-821` 因中文探测内容及规划空响应与预期超时不同而失败，原收据保留，修正独立编排／故障设置后才取得上述合格批次。

独立 GUI 收尾批次 `g3-t03-gui-final-20260919-113233-126` 从仓库外启动，配置文件路径含中文和空格，省略 BaselineRunId 后自动取得新资格 `g3-t01-check-20260919-113233-558`。插件在规划后实际暂停，finish-g3-gui.ps1 核对控制进程身份后请求正常关闭，11:33:51 收尾完成；GUI、UxAS 均退出 0，端口释放，result／entry-result 均 passed，环境恢复通过。该操作记录 manualGuiAcceptance=false，没有冒充用户对最终全程 GUI 的人工确认。

## 4. 问题、限制与后续

- 首轮配置假定 EntityControl 只登记两架实体，实际原文件还列有其他实体端口。改为副本只保留 400／500，逐项显式配置；原文件不变。
- 初次以观察口回显判断控制输入就绪，实际桥过滤自身来源，导致超时。改用 AMASE 实际接收与 UxAS 自身状态，来源改写由独立消息日志见证。
- Python 生成工厂的 unpackFromXMLFile 返回根节点下的消息列表，不直接返回根消息。运行器改用原根节点的 Series／类型创建对象并按生成类读取，没有修补生成输出。最终任务 LMCP SHA-256 为 `0DD74ECBAD645A3F49E51D7498509D551DD72311F3EC114E2E690E2A2A16BE39`，与 T02 实际 C++ 读取原任务 XML 的结果一致，重复 ViewAngleList 的有效内容没有变化。
- 中文目录首轮将目录名用作 KeyValuePair 值，暴露旧字符串长度与 UTF-8 字节长度不一致的边界；此类内容不能当作已验证的任意 Unicode 消息支持。运行标识使用 ASCII，并从真实运行工作目录相对加载 scenario.xml，避免把本机中文绝对路径带入 SessionStatus。通用 Unicode 消息字段支持留给后续消息契约验证，届时按生成器／模板修改并完整重建，不手改生成代码。
- 当前只证明初始化和规划响应。实际规划命令、分段续传、航点／任务关联及轨迹归 T04；任务完成与 20 米栅格统计正确性归 T05。零高程缺省、AllAny 统计分支及旧场景字段风险继续保留。在线重连／快照归 G4，浏览器控制归 G6，G3-T07 仍须取得本轮完整 GUI 人工确认。

总时限审查后补充上述关闭预留，最终以 `g3-t03-test-20260919-113944-818` 重跑完整 11 组矩阵及 10 项反例，均通过；预算耗尽拒绝采用截止时间反例，未实际等待 45 分钟。再以同一新资格完成 GUI 暂停／收尾复验 `g3-t03-gui-budget-20260919-114418-444`，两端退出 0、端口释放、来源与环境恢复通过。本报告最终来源以这两份新收据为准，前一完整通过矩阵与 GUI 收据保留。
