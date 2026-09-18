# G2-T06：HelloWorld 原生运行与验收

日期：2026-09-18，Asia/Shanghai。**T06 已完成，T07 可执行、尚未启动；G2 尚未完成。** 本轮确认真实内部总线双向消息、原配置运行和正常退出，没有启动 AMASE、增加外部 TCP 桥或发布正式 UxAS。

## 实现与复用命令

起点为交接提交 `5c2d38793da755b29a911cb33b598d3f23f1e821`，工作区干净，本地与远程 main 一致。规划复查 `g2-t05-resolve-20260918-175051-762` 通过；Python 3.14.7 x64、固定工具、依赖／LMCP／生成来源和原候选有效，四项 CRT 文件哈希仍与 T05 相同。

[运行入口](../scripts/windows/run-uxas.ps1)和 [验收入口](../tests/windows/uxas-helloworld.tests.ps1)共用 [PowerShell 编排](../scripts/windows/uxas-runtime-common.ps1)、[运行器](../scripts/uxas_runtime/run.py)与 [日志验收器](../scripts/uxas_runtime/analyze.py)。运行编排单独登记 11 项输入，保留现有 T05 来源规则；没有把新增文件塞入会被构建来源全目录扫描的 scripts/uxas。

PowerShell 5.1，以下命令以仓库根为工作目录；本轮也实际从系统临时目录用脚本绝对路径调用：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
$buildRunId = 'g2-t05-build-20260918-195355-288'
$validationRunId = 'g2-t05-test-20260918-195540-900'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-uxas.ps1 -PythonExecutable $pythonExe -BuildRunId $buildRunId -ValidationRunId $validationRunId
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-helloworld.tests.ps1 -PythonExecutable $pythonExe -BuildRunId $buildRunId -ValidationRunId $validationRunId
```

三个来源参数均必填；运行入口的 `-Example` 仅支持并默认采用 `HelloWorld`。入口先调用 `Resolve-UxasCandidate`，执行时与结束时继续复查候选、收据、工具、依赖、生成输入及运行器自身哈希。原 XML 原样复制并核对，保持 EntityID 100、10 秒、1000／5001 ms 和两条文本；没有传入 `-runUntil`。

运行记录位于独立的 `out/runs/g2-t06-{run,test}-<时间>/`。子进程使用参数数组、隐藏窗口和显式工作目录；配置、stdout、stderr、应用 log 和 datawork 均隔离。每例保存 PID、命令、配置与候选哈希、墙钟起止、单调耗时、实际退出码、进程回收和文件哈希。30 秒为进程超时，不含前置来源检查时间；清理只操作本次 Popen 持有的子进程句柄。默认 HelloWorld 仅用内部总线，不借用 AMASE 端口。

读取结果需同时检查 `result.json` 与 `entry-result.json` 成功，后者确认进程环境、工作目录、控制台编码恢复及用户／系统 PATH 未变。验收另写 `acceptance.json`，由 result 绑定其哈希，再关联各例原始文件和运行脚本来源；它不是正式 UxAS 发布收据。

## 首次诊断与必要修正

首次运行 `g2-t06-run-20260918-194827-987` 使用原 T05 候选。实际 stdout 已出现 13 条两个方向的接收，进程耗时 12.223 秒、退出 0；但验收为 **failed**，因为缺少配置加载、服务创建和详细退出日志。该记录保留，没有用后续解析规则回写成功。

源码确认 `UxAS_Log.h` 默认将普通 `UXAS_LOG_INFORM` 编译为空，只有部分专用 INFO 日志保留。为满足来源与生命周期证据要求，[Uxas.cmake](../cmake/Uxas.cmake)只为 uxas 目标定义已有的 `UXAS_INFO_LOGGING_ENABLED`；没有开启 DEBUG、改变消息、定时器、算法、服务注册或原 XML。控制台原有 WARNING 过滤保持，新增 INFO 进入应用文件日志。

CMake 输入因此改变，按原入口重新完成 T03 → T04 → T05，使用新的候选双编号。原候选和历史清单保留；不能再用原交接候选绕过当前来源检查。这是 T06 必要证据修正引起的前置复验，不是 T07 发布任务。

| 复验项目 | 实际编号／结果 |
| --- | --- |
| C++ LMCP 构建／完整验收 | `g2-t03-build-20260918-195001-565`／`g2-t03-test-20260918-195057-347`；原入口退出 0，七模型、三语言双向样本、错误拒绝、VS／Ninja 迁移消费通过 |
| UxAS 配置／完整验收 | `g2-t04-configure-20260918-195135-036`／`g2-t04-test-20260918-195240-495`；原入口退出 0，配置图、10 个独立桥探针、15 项隔离故障通过 |
| UxAS 候选构建／完整验收 | `g2-t05-build-20260918-195355-288`／`g2-t05-test-20260918-195540-900`；原入口退出 0，普通／中文路径干净构建、平台、实际 CRT、来源和 11 项故障通过 |
| 当前 exe SHA-256 | `4BB94E29FD49689A84845F7254663655740F32F8F42595BDD1896B74416AFD9F` |
| 当前候选 build-info SHA-256 | `775FA96AB5771A4823EF152143D9753448479D4DE222541CC5F352160EF5973E` |
| 当前 LMCP build-info SHA-256 | `27014C024F4E7733E3860DAAF5E7D8055E5F5292A6E89497CF13BA55DD97F849` |

## T06 实测结果

自动验收 `g2-t06-test-20260918-195743-715` 退出 0。普通和中文空格运行目录均从原 XML 创建两个服务，应用日志按创建顺序确认 `51 = Hello from #1`、`52 = Hello from #2`。两例各记录 `51→52` 10 条、`52→51` 3 条，自收计数 0，未解析接收片段 0。计数是本次观察值，不是以后必须精确匹配的门槛。

| 用例 | 结果 |
| --- | --- |
| 普通目录 | 进程 12.249 秒；ServiceManager 日志区间 10244 ms；退出 0，无强制终止，进程已回收 |
| 中文空格目录 | 进程 12.231 秒；ServiceManager 日志区间 10230 ms；退出 0，无强制终止，进程已回收 |
| 缺失配置 | 真实 uxas.exe 返回 100，诊断绑定本次缺失路径，在网络／服务启动前拒绝 |
| 关闭的串口桥 | 真实 uxas.exe 返回 300，包含 LmcpObjectNetworkSerialBridge 和 UXAS_ENABLE_SERIAL=OFF，在启动前拒绝 |
| 关闭的 Zyre 桥 | 真实 uxas.exe 返回 300，包含 LmcpObjectNetworkZeroMqZyreBridge 和 UXAS_ENABLE_ZYRE=OFF，在启动前拒绝 |
| 日志验收器 | 13 个反例被拒绝；1 个“完整真实记录加损坏片段”对照通过并报告片段，见 [反例实现](../tests/uxas_runtime/checks.py) |
| 超时清理 | 同一运行器对自己启动的 Python 睡眠辅助进程施加 0.2 秒超时，保留 failed／timedOut／forcedTermination，确认回收；不是 UxAS 超时矩阵证据 |

验收器保留完整消息的原始字节范围，按本次服务 ID 与原配置绑定文本，要求两个方向至少各一条。自收不计通过，完整记录中的错误 ID／文本直接拒绝，不拼接损坏片段。反例包括只有启动、只有自收、单向、错误文本／发送者／接收者、缺失退出证据、非零退出、提前／强制退出、错误配置／时长和不完整消息；这些内存派生样本不作为通信证据。

生命周期检查同时要求实际加载路径、原时长、两个服务启动、至少 10000 ms 的服务运行区间、按时长终止、全部服务与 ServiceManager 客户端退出、无应用 ERROR 和主进程退出 0；不单凭关闭横幅判断成功。源日志毫秒值保留为字符串，进程耗时另用单调时钟记录。

独立运行入口的最终复查为 `g2-t06-run-20260918-195918-390`，退出 0，正常双向接收和完整退出通过，环境恢复通过。普通、中文以及独立运行均使用新候选；自动验收前后的全部来源保持。T06 验收收据 SHA-256：`C355A787B36B87BC2B19C234C561B850D07FD217E061657ABF4BE91AF23A23F1`。

## 后续边界

T06 的错误配置用例保留程序失败状态，并另记 expectedFailureVerified；超时辅助进程也保留失败，不把预期故障改成程序通过。旧 T03／T04／T05 专题报告保持历史快照，本页提供最新批次交接。

T07 尚未启动：还需按任务卡执行完整复验、连续三次正常启停、完整故障矩阵和正式发布；本轮没有建立 out/artifacts/uxas。AMASE↔UxAS、WaterwaySearch、外部协议和完整重连仍归后续任务。过程与归档结果见 [worklog](../worklog.md)，当前进度见 [status](status.md)。
