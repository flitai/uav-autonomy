# G3-T06：稳定性与故障复验

日期：2026-09-19，Asia/Shanghai。**G3-T06 已完成。** 10 个独立运行、6 项隔离来源检查、8 项重放对照及总预算检查通过；T07 可执行、尚未启动，G3 阶段仍未完成。

## 1. 范围与入口

本卡复用 T05 的正式 AMASE／UxAS／同批 LMCP、原 WaterwaySearch XML 和业务参数，独立验证连续短程执行、路径、故障拒绝、断线清理及整组重启。新增 [配置](../config/g3-stability.json)、[运行入口](../scripts/windows/run-g3-stability.ps1)、[验收入口](../tests/windows/g3-stability.tests.ps1)、[编排](../scripts/g3_stability/runtime.py)和 [矩阵](../tests/g3_stability/checks.py)。没有修改业务源码、旧入口、生成输出或正式来源清单。

正常轮次复用 T03 的真实初始数据与单次任务请求屏障，以及 T04 的分段命令、AMASE 内部导航和轨迹关联；至少四个任务目标、两条实际推进航段及两个分段命令才可通过。每次以独立新运行编号和 Python 控制器启动整组进程，默认固定 1 倍，仍保留原 785 秒场景。**短程检查不替代 T05／T07 全程任务及覆盖统计。** 不设置最低覆盖率，不开展算法或参数寻优。

T05 正式 GUI 的 1→5→10 倍已由用户单次接受，详见 [T05 报告](g3-completion-validation.md)；本卡不扩大该例外。运行中检查 AMASE 的真实 Running SessionStatus，并在退出后重新审计实际倍率，变化会明确失败。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
# CompletionRunId 必须是与当前正式产物及配置一致的 T05 合格批次。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-stability.tests.ps1 -PythonExecutable $pythonExe -CompletionRunId g3-t05-test-20260919-154803-742
# 单次短程；可选 -ChinesePath 验证中文空格应用目录。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3-stability.ps1 -PythonExecutable $pythonExe -CompletionRunId g3-t05-test-20260919-154803-742 -Mode Headless
```

入口以脚本位置解析仓库；默认重新执行 T01 只读资格检查，也接受明确的 BaselineRunId 并再次校验实际输入。Configuration 默认 `config/g3-stability.json`，只接受冻结策略。`-TestFault` 只用于单次诊断，底层以非零退出并保存 failed；正式矩阵在上层判断是否符合预期。每个矩阵子运行保存自己的 result、case-result、控制器日志、PID／退出状态和实际工作目录；Windows 父入口单独保存环境／工作目录／编码恢复与持久 PATH 检查。

## 2. 输入身份与先行诊断

起点 `e1c2c83050b6e22ac638bfa4439301b09f45ea13`，工作区干净。新输入资格 `g3-t01-check-20260919-162134-898` 通过，仍为 inputRevision=3、acceptanceRevision=2、43 项冻结输入。

| 输入 | 本轮固定身份 |
| --- | --- |
| T05 前置 | `g3-t05-test-20260919-154803-742`，两模式完成／统计及正常退出，逐项复核原始证据摘要 |
| AMASE | `g1-t04-build-20260919-132521-005392`；JAR `4C96DAF2D72DEB826940294B1566037F0B500940958352CCFE6DBCD77A0DBAC7` |
| UxAS | 发布 `g2-t07-publish-20260919-154459-188`；EXE `036EA32D168859B089969F4EA24431BB52F9302B65C1EC185EA0A82D77CFA366` |
| 工具 | Windows 原生 Python 3.14.7 x64／隔离模式、Temurin 11.0.32.1+1；复用合格工具／CRT，不更改持久环境 |

先行断线诊断 `g3-t06-diagnostic-disconnect-20260919-165300` 按预期 failed；手工编号不代表实际开始时间，真实收据为 16:32。在流偏移 10037 处，将一条 579 字节状态帧仅转发 289 字节后关闭主链路，保留完整源帧、已发送前缀和未转发部分长度。AMASE／UxAS 均正常退出 0，无强制终止，端口释放。该诊断只验证故障路径，不能代替完整矩阵。

## 3. 矩阵与证据规则

正式矩阵 `g3-t06-test-20260919-164024-586` 从仓库外工作目录 `out/tmp` 调用，result／entry-result／acceptance 均 passed，入口退出 0，耗时 685.84 秒。六项故障子运行仍为 failed／退出 1，矩阵单独确认其预期拒绝；四组正常运行均 passed／退出 0。

各子编号均为上述矩阵编号加下表后缀。四组正常执行均关联分配实体 400、任务 1000、两个真实分段命令、四个公开任务目标和至少两条实际推进航段；实体 500 持续提供真实动态状态。公开状态目标为 14／15／16／18，内部导航包含采样间经过的 17，沿用 T04 的关联判据。

| 子编号后缀 | 模式／路径 | 收尾仿真秒 | AMASE／UxAS PID | 结果 |
| --- | --- | --- | --- | --- |
| repeat-1 | 无界面、其他工作目录 | 121.97 | 28612／3000 | 正常实际执行 |
| repeat-2 | 无界面、中文空格工作与应用目录 | 121.99 | 28104／5512 | 正常实际执行 |
| repeat-3 | GUI、其他工作目录 | 121.98 | 27828／27860 | 正常实际执行 |
| fresh-group | 断线后新编号、中文空格目录 | 121.94 | 24420／27720 | 新组实际执行 |

每组正常执行捕获 238 条 Running SessionStatus，全部为 1.0；均正常退出 0、无强制终止、进程回收、端口释放，未产生 TaskComplete。该结果证明短程执行与运行隔离，不是全任务完成声明。

| 类别 | 检查与通过规则 |
| --- | --- |
| 连续三次 | 无界面、中文空格目录无界面、GUI 顺序运行；每次重新初始化并到达实际任务航段，退出 0、无强制终止、进程与端口回收 |
| 来源隔离 | AMASE／UxAS 缺失与损坏副本、UxAS 混批身份、LMCP 混生成批次；生产校验器拒绝，原始子记录保持 failed |
| 端口占用 | 矩阵父进程持有监听口，子运行在启动应用前拒绝；占用者与监听连接保持 |
| 提前退出 | 分别让所属 AMASE、UxAS 在完成规划但尚未实际执行时正常退出；即使退出码为 0，也判定当前任务失败 |
| 超时 | 规划 30 秒超时后正常收尾；关闭 30 秒超时只强制回收本次 AMASE，保留非零退出及失败状态，不计作正常退出通过 |
| 断线 | 测试用主链路转发器在真实 AirVehicleState 帧中途截断；记录完整帧、前缀、偏移，当前组失败并清理；端口 5557 显式检查归属与释放 |
| 新组恢复 | 新运行编号、进程、独立解析器、零起始仿真时刻和本次就绪 token；原任务／请求重新单次触发，新的真实航段关联通过 |
| 反例 | 基于新组真实记录检查变速、旧就绪 token、字节偏移、时钟、任务、命令、完成污染；内存变异与真实后端故障分开记录 |

底层失败的 result／case-result 与上层 `expectedFailureVerified` 分开，不能将故障子记录重写为 passed。正常收尾保留每个 PID、退出码、reaped／forcedTermination 和端口状态。原始帧、事件、导航、UxAS SQLite 日志、配置差异和类加载来源在各自独立 `out/runs/<run-id>/` 中，受既有忽略规则保护。

断线转发器只在故障例启用，普通运行和新组仍采用真实 AMASE↔UxAS 直连。原场景的实体／任务／命令数字 ID 可在新运行复用；隔离通过运行身份、零时刻、独立原始流、来源比对和注入顺序确认，不能把“数字 ID 相同”误判为旧任务续跑。未实现在线自动重连、快照补齐或断点续跑。

实际故障结果：端口 5556 占用在应用启动前拒绝，父矩阵监听器仍可连接；AMASE／UxAS 提前退出分别以 `process-exited:<pid>` 拒绝，尽管被注入的提前退出码均为 0。规划超时保留 `timeout:planning-response` 并正常关闭两进程；关闭超时在 30.026 秒回收本次 AMASE PID 17144（退出 1、forcedTermination=true），UxAS PID 2728 正常退出 0，关联的连接重置诊断保留。该故障例不计作正常退出通过。

正式断线例截断实体 400、仿真时间 4709 毫秒的真实 AirVehicleState：此前完整转发 26 帧，在流偏移 10037 保留 289 字节前缀，源帧共 579 字节。独立严格解析返回 `Truncated Sentinel frame at EOF`，该残缺状态未进入 UxAS。完整源帧、实际接收流相应范围和截断前缀逐字节一致；失败组清理后，fresh-group 使用不同 PID、新就绪 token、从字节偏移 0 开始的解析器及零起始仿真时间完成实际执行，没有旧任务／命令／完成污染。相应原样与七项内存反例通过。

输入与环境收尾：正式 AMASE／UxAS 包、当前指针、统一 Java 消息库、43 项冻结输入及 T05 收据前后摘要相同，新增编排输入未变化。父入口环境／工作目录／控制台编码恢复，持久 PATH 保持。`out/tmp/g3-t06-final-evidence.json` 独立核查 658 项文件摘要及层级收据绑定；acceptance SHA-256 为 `E7E5F0B146421C76BB7AC24BB56670A85F1FE0E1F81F3E356304F8BC6A76E53A`。普通运行无强制终止；关闭超时故障的强制回收单列，不隐藏其 failed 状态。

## 4. 纠正记录与交接

早期矩阵 `g3-t06-test-20260919-163443-663` 的第一轮已到达真实执行并正常退出，但新增隔离检查把原巡航的 UxAS 重编号误判为污染。源码及原始 XML 确认 WaypointPlanManager 会重编号／批准，并附加配置中的默认无任务云台动作；检查现按本轮原巡航内容对应，只识别这项精确既有转换，其余航点／位置／速度／任务内容仍须相同。旧规划命令的真实捕获反例保持拒绝。随后 `163900-514` 的首轮误在离线检查失败尚未核对时启动，已通过所属运行 request-abort 正常停止；底层 `timeout:parent-budget` 在此表示主动请求收尾，不是实际耗尽预算。两组 failed 保留，未改写为通过。

`g3-t06-isolation-diagnostic-20260919-164008` 已通过原样重放与七项污染／倍率反例。入口补充检查 `g3-t06-entry-check-20260919-164238-155` 从 `out/tmp` 调用，缺少 Python、重复编号及不存在的 T05 前置均拒绝；子记录 failed 保留，重复编号没有改写历史结果，环境／目录／编码恢复及持久 PATH 检查通过。首次辅助检查遇到 PowerShell 对子进程预期 stderr 的终止处理，修正辅助脚本的捕获方式后用新编号重试，未改变正式入口。

T06 完成，无需变更或重新发布正式二进制；新增编排独立于 T03～T05，旧验收输入和历史报告保持。T07 可执行，仍须冻结配置的 GUI／无界面最终全程、本轮 GUI 人工确认及正常退出；本卡 GUI 自动短程不代替人工确认。T07 应核对本报告矩阵、T05 完整任务／覆盖证据和当前实时来源，不能复用旧 GUI 确认或单次倍率例外。G3 阶段仍未完成，在线恢复／快照归 G4，重置分段归 G6。无 DTED 的零高程条件保持，不宣称实地覆盖验证。
