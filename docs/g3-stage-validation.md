# G3-T07 阶段验收与 G4 交接记录

日期：2026-09-19（Asia/Shanghai）。当前状态：**G3-T07 已完成，G3 阶段验收通过**。最终两模式运行 `g3-t07-test-20260919-173116-474` 的 result／entry-result／acceptance 均 passed；本轮 GUI 人工确认及正常退出完成，G4 待细化、尚未启动。

## 1. 范围与入口

本卡复查 T01～T06 证据链，在冻结业务配置下分别完成 Windows 原生无界面／GUI 全任务，复核真实末端、可靠 TaskComplete、20 米逐格覆盖与报告。GUI 先形成可审查结果，取得本轮人工确认后正常关闭；全部通过后输出机器可读交接和 [G4 交接说明](g3-g4-handoff.md)。

没有修改业务源码、原例 XML、算法／传感器参数、MDM／生成文件、正式包及 T03～T06 实现。保留 90 点完整水道、785 秒场景和 1 倍运行；覆盖率没有最低门槛。T05 的单次变速接受只保留为历史，本次直接核对全部实际 Running SessionStatus，倍率变化即失败。

新增文件：

| 文件 | 职责 |
| --- | --- |
| [config/g3-acceptance.json](../config/g3-acceptance.json) | 阶段策略、唯一连接／执行／完成配置路径、历史证据身份 |
| [runtime.py](../scripts/g3_acceptance/runtime.py) | 两模式全程、不可变 GUI 审查快照、确认等待与交接 |
| [receipts.py](../scripts/g3_acceptance/receipts.py) | T01～T06 收据、当前来源与人工确认绑定检查 |
| [finish.py](../scripts/g3_acceptance/finish.py) | 绑定实际用户回复，核对运行中控制器后请求正常收尾 |
| [checks.py](../tests/g3_acceptance/checks.py) | 当前确认与旧／错身份拒绝对照 |
| [run-g3-acceptance.ps1](../scripts/windows/run-g3-acceptance.ps1)／[验收入口](../tests/windows/g3-acceptance.tests.ps1) | 正式来源解析、隔离解释器、环境恢复及独立运行编号 |
| [finish-g3-acceptance.ps1](../scripts/windows/finish-g3-acceptance.ps1) | 本轮 GUI 确认后的收尾入口 |

运行命令从仓库根目录调用；脚本从自身位置解析仓库，也支持其他工作目录。PythonExecutable 必须指向实测可用的 Python 3.14.7 x64：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-acceptance.tests.ps1 -PythonExecutable $pythonExe -StabilityRunId g3-t06-test-20260919-164024-586
# 控制台打印 G3_T07_GUI_READY 后，先取得该次 GUI 的真实人工确认，再执行：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\finish-g3-acceptance.ps1 -PythonExecutable $pythonExe -RunId '<本次 G3-T07 编号>' -ConfirmationText '<本轮真实用户回复>'
```

验收入口接受可选 Configuration、RunId 和 BaselineRunId，当前策略必须匹配冻结的四个配置；StabilityRunId 为必填合格 T06。省略 BaselineRunId 时重新运行只读输入资格检查，不能永久复用历史身份。运行目录已有时明确拒绝。不得在未收到用户回复时自行填入确认文字。

## 2. 输入资格与历史证据

起点提交 `6c0294e3b86c0519d4752b8b8ea8404962cc6c16`，工作区干净。固定工具实测通过，新资格 `g3-t01-check-20260919-172312-180` 的 result／entry-result 均 passed。inputRevision=3、acceptanceRevision=2，43 项冻结输入。

| 层次 | 本轮绑定身份 | 核查内容 |
| --- | --- | --- |
| T01 | `g3-t01-check-20260919-172312-180` | 当前工具、正式包、同批消息与冻结输入 |
| T02 | `g3-t02-verify-20260919-104721-817` | 历史双向协议、来源／过滤及故障样本；收据与原始文件摘要保持 |
| T03 | `g3-t03-test-20260919-113944-818` | 历史初始化和反例；当前编排输入一致 |
| T04 | `g3-t04-test-20260919-121531-644` | 历史分段／实际执行；当前编排输入一致 |
| T05 | `g3-t05-test-20260919-154803-742` | 当前正式版本全任务与逐格复算，父级／案例／原始文件摘要 |
| T06 | `g3-t06-test-20260919-164024-586` | 当前正式版本 10 个子运行、6 项来源反例、恢复及保护摘要 |

T02～T04 运行使用的旧 AMASE 构建身份明确保存为 historicalAmaseBuildRunId，不冒称已在新二进制上重跑。T05 四项 AMASE 修复已经过 G1 重建／11 组自动复验／真实 GUI 确认／发布，以及 G2 交接更新。当前全程继续消费该正式版本：

| 产物 | 身份 |
| --- | --- |
| AMASE 构建 | `g1-t04-build-20260919-132521-005392` |
| AMASE 正式收尾 | `g1-t04-finalize-20260919-154103-934413` |
| AMASE JAR SHA-256 | `4C96DAF2D72DEB826940294B1566037F0B500940958352CCFE6DBCD77A0DBAC7` |
| UxAS 构建／候选验收 | `g2-t05-build-20260919-101514-494`／`g2-t05-test-20260919-101831-478` |
| UxAS 复验／正式发布 | `g2-t07-test-20260919-154235-410`／`g2-t07-publish-20260919-154459-188` |
| UxAS EXE SHA-256 | `036EA32D168859B089969F4EA24431BB52F9302B65C1EC185EA0A82D77CFA366` |

完整来源、同批 LMCP 运行身份、正式路径和运行配置摘要由本次 context／result／prior-receipts 保存；最终 handoff 只在阶段通过时生成。本卡没有新的业务构建输入，不重复发布未改变的二进制，也不改写旧来源清单。

## 3. 实际验证与当前结果

只读预检 `g3-t07-preflight-20260919-173023` 通过现有插件编译、覆盖／末端夹具、T01～T06 收据链和 12 项确认绑定检查。明确记录 qualified-only、simulationStarted=false、stageAccepted=false，不计入正式全程结果。

正式命令从 `out/tmp` 调用绝对路径的 Windows 验收入口，绑定上述新资格和 T06 编号，运行编号 `g3-t07-test-20260919-173116-474`。原始证据位于 `out/runs/<该编号>/`。

入口检查 `g3-t07-entry-check-20260919-173945` 从其他工作目录验证缺解释器、重复编号、缺合格 T06：三项均明确拒绝，环境恢复、历史收据保持、无业务进程启动通过。失败子收据保留，未冒充全程通过。Python／PowerShell 语法、文档 UTF-8 与链接、历史工作日志前缀及 T03～T06 输入／报告保护已检查。

| 项目 | Headless | GUI |
| --- | --- | --- |
| 当前状态 | passed，已正常收尾 | passed，本轮确认后正常收尾 |
| 完整任务／末端与 TaskComplete | 目标 14～73 全部执行；末端 740.310 秒到达，完成 740709 仿真毫秒 | 目标 14～73 全部执行；末端 740.310 秒到达，完成 740709 仿真毫秒 |
| seen／total、逐格独立复算 | 724／724，100%；2794 条任务后状态独立复算一致 | 724／724，100%；2794 条任务后状态独立复算一致 |
| 同记录 GUI／headless 重放 | 逐格一致；重复报告、清空重放一致 | 逐格一致；审查前及退出后均通过 |
| 实际倍率／正常退出／端口释放 | 1405 条 Running 均 1.0；两个进程退出 0、无强制终止、端口释放 | 1405 条 Running 均 1.0；两个进程退出 0、无强制终止、端口释放 |
| 实际收尾仿真时间 | 744.030 秒 | 744.020 秒 |

无界面实际收尾时间约 744.030 仿真秒；任务 1000 分配给 400，末段保留 45 个导航样本，前向推进约 223.997 米，到达时距目标约 3.728 米。TaskComplete 由 100/66 发出，时间与首个退出任务状态 740709 毫秒一致。100% 为本次计算结果，不是门槛或调参目标；使用现有零高程缺省。

最终验证已通过并分别保留：19 项覆盖小样本、6 项末端导航夹具、基于本轮真实记录的 19 项完成／统计正反例，以及 12 项 GUI 确认绑定正反例。这些检查不替代两次真实全程。有效零覆盖的正确报告可通过；空统计、缺末端、重复／错任务／提前完成、计数／百分比／坐标／导出错误必须拒绝。

## 4. GUI 审查与正常收尾

GUI 完成后显式等待网络 SessionStatus 进入暂停，快照保存观察流、AMASE 状态、内部事件与导航，再复核完整执行、逐格覆盖和同记录两环境 Java 重放。review.json 明确 normalExitValidated=false、manualGuiAcceptance=false，只有自动审查通过，不能据此完成阶段。

gui-ready.json 绑定本次 runId、控制器／AMASE／UxAS PID、随机 nonce、审查摘要及就绪时间。人工等待独立计时，按 [阶段方案](g3-system-integration-plan.md#初始化与生命周期) 排除在 2700 秒自动预算之外；仍持续检查进程、连接、倍率和暂停时刻，恢复运行、重置或退出均不视为确认。

收尾入口要求非空真实用户回复，复核当前控制器命令、review 及全部快照摘要，生成本次 request-gui-acceptance.json。错运行、错 PID、错 nonce、旧摘要、早于就绪时间、自动或空确认均拒绝。此绑定用于防止误复用，不是用户身份认证系统。

本次 gui-ready 身份为控制器 PID 5928、AMASE PID 18196、UxAS PID 13784；审查摘要 `C3F2F29015AB54A06C6AAC6D90121BA4363E77BE58279D189B83DD9D441CD3F1`。用户已对当前运行作出真实确认；原就绪和审查记录保留，最终确认与退出收据另行绑定。

收到有效确认后才请求 AMASE 正常关闭及 UxAS KillService，继续复核退出码、无强制终止、端口释放、全程统计与审查结果一致。结果与 entry-result 都 passed、acceptance／handoff 摘要一致后才登记 G3 完成。本轮用户于 2026-09-19T17:58:52.068415+08:00 确认“本轮 GUI 正常，确认并正常退出”，收尾绑定当前运行与审查摘要，两个应用正常退出。自动墙钟耗时 1540.591 秒，独立人工等待 131.658 秒，自动预算通过。

## 5. 交接与边界

连接、消息方向、初始数据、时间、协议样本和恢复缺口见 [G4 交接说明](g3-g4-handoff.md)。合格交接的依据是明确运行编号下的 result／entry-result／acceptance／handoff 及配置摘要，不按目录修改时间选择“最新”输出。

当前没有消息网关、Cesium 或训练适配实现；观察／控制客户端是本地验收工具。在线自动重连、快照与增量补齐、完整恢复矩阵归 G4；重置／场景切换的时间分段归 G6。保留零地形缺省、Unicode 业务字段与第二机器／离线部署限制。实际覆盖百分比只作为后续研究基线，不代表真实地形或任意场景效果。

本轮 acceptance SHA-256：`E8276885EBC323949693DE2C16CCF014B3602AF35A11A1F814D1317A6E24869B`；handoff SHA-256：`B173FE908E612470CAB35652C3EA8409A293D039960124BE4BA2D168BD4C4BD3`。独立 `out/tmp/g3-t07-final-evidence.json` 复核 423 条摘要及确认／退出／历史收据绑定，通过。正式包、当前指针、43 项冻结输入及 T03～T06 实现保持，进程环境、工作目录、编码与持久 PATH 恢复通过。归档结果见工作日志 WL-20260919-010。
