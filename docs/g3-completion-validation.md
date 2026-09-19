# G3-T05 任务完成与覆盖统计正确性

日期：2026-09-19，Asia/Shanghai。**G3-T05 已完成。正式 GUI／无界面完整任务、可靠 TaskComplete、覆盖统计独立复算和正常退出通过；新 AMASE 本轮 GUI 确认／发布、UxAS 交接更新和当前来源资格已完成。** 原始诊断、失败对照和既往收据保持。

## 1. 范围和实现

保留 WaterwaySearch 原 XML、400／500 实体、90 点完整水道及点序、785 秒场景、默认启动 1 倍速和业务参数；本轮正式 GUI 的实际变速及用户明确接受见第 5 节。不设最低覆盖率，不进行算法／参数寻优。新增 [完整任务入口](../scripts/windows/run-g3-completion.ps1)、[两模式验收](../tests/windows/g3-completion.tests.ps1)、[冻结配置](../config/g3-completion.json)和 [编排](../scripts/g3_completion/runtime.py)，复用 T03 初始化与正常关闭、T04 规划／分段／导航关联。

独立 [完成检查](../scripts/g3_completion/completion.py)要求实际分配实体依序经过所有任务目标，具有末段轨迹和内部 `waypointReached`，再关联退出任务状态及唯一、同源、同任务／实体的 TaskComplete。`TimeTaskActivated`／`TimeTaskCompleted` 在该配置中来自 Test_SimulationTime 驱动的离散仿真毫秒；源码方法名中的 UTC 不代表这些值是日历时间。

[导出插件](../scripts/g3_completion/CompletionProbe.java)在真实应用暂停后调用原 AnalysisManager，保存分析 XML、全部原始栅格和事件记录。报告新增 seen／total；[独立复算](../scripts/g3_completion/coverage.py)检查完整水道分母、坐标、相机足迹、波段和 GSD，输出漏覆盖位置 CSV。相同事件分别以 GUI／无界面 JVM 调用 AnalysisManager，比较每格结果、报告、重复导出和重放结果。两次真实飞行分别统计，不合并。

## 2. 修复前证据与最小修复

起点 `f357e96d96d085a8dccfb406d1b917c72991b2aa`，工作区干净；本轮原资格 `g3-t01-check-20260919-130929-695` 通过。

| 原问题 | 实测依据 | 本轮修复 |
| --- | --- | --- |
| 末段提前完成 | 原版 `g3-t05-original-20260919-131200` 约 730.039 秒发送 TaskComplete；最后任务目标 73 仅记录一个约 0.03 秒样本，随后进入同坐标、无任务的 74。独立审计 `g3-t05-original-completion-audit-20260919-132500` 以缺末段执行证据拒绝 | WaypointFollower 仅在任务末点转入同坐标、无任务、自循环标记时使用已有 fly-past 到达判定。普通 TurnShort、规划、分段／重叠和业务参数保持 |
| AllAny 被错误拒绝 | `g3-t05-original-coverage-20260919-131500`：已知 3 格应全部覆盖，实际 0；MDM 定义 AllAny 为波段不适用，SearchTask 默认也是 AllAny | LinearSearchHighlight 把“既不匹配具体波段也不是 AllAny”作为拒绝条件；足迹、GSD 和停留条件保持 |
| 20 米分辨率被静默粗化 | 同一对照中约 1.1 公里线段应有 56 格，原来只有 10 格。完整水道 16 段受影响，原分母 669，20 米分母 724 | 删除线搜索每段最多 10 格限制，保留原有分段插值与取样位置，不删减水道 |
| 无界面分析创建窗口 | 原 AnalysisManager 在 headless 对照中抛出 HeadlessException | 无界面不创建进度窗口；GUI 的进度窗口在 finally 中释放；分析客户端取得其实际配置 |
| 报告不可独立核对 | 原报告只有格式化百分比 | SearchTaskAnalysis 输出原始 seen／total 和独立全部栅格明细，使用稳定小数格式；分析重放清理相机／时间状态 |

正式业务源码只改上述四个 Java 文件；没有修改 UxAS、MDM、生成器或生成输出。统计修复限于本任务使用的线搜索；不宣称区域／点搜索分支均已验证。

## 3. 对照与发布复验

[覆盖小样本](../tests/g3_completion/CoverageChecks.java)包括已知未覆盖、2／3 部分覆盖、全部覆盖、重复观测、足迹外、GSD 边界、EO／LWIR／AllAny、毫秒停留边界、长线 20 米、无界面分析、配置传递和重复报告。[末端样本](../tests/g3_completion/TerminalChecks.java)使用真实 WaypointFollower 验证到达前不结束任务、飞越后推进并解除任务、原普通 TurnShort 不变。

`g3-t05-candidate-checks-20260919-132900`：同一组测试对旧 JAR 的覆盖／末端各检出 3 项失败，对新候选全部通过。此前 `132700` 的末端测试因测试实体尚未创建事件管理器而抛出空指针，属于夹具缺陷；改用独立 EntityData 夹具后重新运行，没有改写原日志。

同一原版飞行记录的 `g3-t05-replay-original-events-20260919-133000`：旧 JAR GUI 为 0／669；新候选 GUI、无界面均为 724／724，逐格一致。独立 Python 复算 2942 条任务后状态也得到 724／724。这是同一记录的统计正确性对照，**不替代新版本两模式真实完整执行**。

新候选构建 `g1-t04-build-20260919-132521-005392`，JAR SHA-256 `4C96DAF2D72DEB826940294B1566037F0B500940958352CCFE6DBCD77A0DBAC7`。`g1-t04-automatic-20260919-132647-813805` 的 11 组自动验收通过；用户本轮明确回复“GUI 人工确认及正常退出  ，一切正常”，`g1-t04-finalize-20260919-154103-934413` 已绑定 GUI `g1-t04-run-20260919-132541-198195` 的退出 0／端口释放证据并正式发布。该确认只对应新 AMASE 发布，不能替代 G3-T07 的完整阶段 GUI 确认。

## 4. 候选全程诊断与入口边界

未发布候选的无界面长程诊断 `g3-t05-candidate-diagnostic-20260919-133400` 已通过，明确 `candidateMode=true`、`formalPublicationValidated=false`，不替代新正式来源资格。真实执行约 744.01 秒后正常退出；末段 45 个样本、前向推进 223.997 米，原生末端到达约 740.310 秒，距末点 3.728 米；首个退出任务状态及 TaskComplete 均为 740709 仿真毫秒。seen／total 为 724／724，独立复算 2794 条任务后状态一致，相同事件在 GUI／无界面 JVM 重放逐格一致。两进程退出 0，无强制终止，端口释放。

`g3-t05-offline-controls-20260919-134700` 的 19 项离线检查通过：原样正向重放，缺失／重复／错误任务／错误实体／提前完成、缺末端导航／任务目标／公开状态、末段静止，空统计／越界／负数／错误百分比、漏导出／错误坐标／错误报告任务／原始已见计数不符均拒绝；有效零覆盖统计可通过算术与导出一致性检查。它们是对真实记录的内存反例，不冒称后端故障注入。

GUI 候选长程诊断 `g3-t05-candidate-gui-20260919-134600` 也已通过：任务目标 14～73 全部依序执行，末段 45 个样本，原生到达约 740.310 秒、距末点 3.728 米，首个退出任务状态与唯一 TaskComplete 均为 740709 仿真毫秒。724／724 格、2794 条任务后状态独立复算、相同事件两种 JVM 重放及重复导出全部一致；AMASE／UxAS 退出 0、无强制终止、端口释放。为保留本轮 G1 发布确认窗口，显式使用 AMASE 5557、实体 29400／29500、观察口 9998，配置快照和端口归属独立留存；不静默替换占用端口。界面截图与响应检查已留证，不替代人工确认。该临时诊断沿用 T04 context 模板，模板中的 mode／verify 字段不是本次运行参数；本次模式以 case-result、真实启动命令和配置快照为准，旧记录不改写。

这两次是发布前的新候选真实完整飞行；后续正式发布、来源资格和标准入口收尾见第 5 节。当前使用原 785 秒、1 倍速，完成后约 744 秒暂停收尾，不为提高覆盖率延长时间。无 DTED 时沿用零高程缺省；独立复算检查捕获的相机足迹为零高程，该结果不是实地覆盖保证。100% 是本轮结果，不是门槛，也未用来寻优。

入口拒绝检查 `g3-t05-entry-controls-20260919-134900` 已验证仓库外调用、缺失 Python 拒绝与环境恢复，以及重复编号拒绝并保持原收据；缺失解释器的 failed 子记录保留。Python／PowerShell 语法、UTF-8、文档链接及差异检查通过，不把静态检查计作正式入口全程验收。

标准入口 `g3-t05-stale-source-20260919-140400` 实测拒绝当前源码配旧来源：result／entry-result 均 failed，诊断为 AnalysisManager.java 输入摘要不匹配，未启动应用；环境恢复通过。这是预期来源拒绝，不是正式全程通过。

## 5. 正式发布、资格与两模式验收

新 AMASE 已依据本轮真实人工回复完成发布。首次新资格 `g3-t01-check-20260919-154113-520` 因 UxAS 已发布 handoff 仍绑定旧 AMASE 而失败，原记录保留。按既有流程执行 `g2-t07-test-20260919-154235-410`，连续三次启停、中文路径、真实超时及隔离故障矩阵通过；`g2-t07-publish-20260919-154459-188` 完成发布目录运行、环境恢复和正式指针更新，旧包与指针备份保留。UxAS EXE SHA-256 仍为 `036EA32D168859B089969F4EA24431BB52F9302B65C1EC185EA0A82D77CFA366`，没有重新编译或修改其源码。

`config/g3-baseline.json` 的 inputRevision=3 保留 revision 2 和旧摘要，只登记四项已复验 AMASE 修复，仍为 43 个冻结输入；acceptanceRevision=2 和无最低覆盖率保持。`g3-t01-check-20260919-154623-382` 的 result／entry-result 均 passed，绑定新 AMASE、更新后的 UxAS handoff、同批七模型、工具／CRT 及原场景。

从仓库外 `out/tmp` 调用标准 Windows 验收入口，正式批次 `g3-t05-test-20260919-154803-742` 的 result／entry-result 均 passed，退出 0。两模式顺序运行，分别使用正式默认端口，不再占用候选诊断端口。入口实际复查正式来源并编译独立插件，完成全程后核对输入未变化。

| 模式 | TaskComplete 仿真毫秒 | 原生末端距目标（米） | 收尾仿真秒 | seen／total | 独立重放状态数 |
| --- | --- | --- | --- | --- | --- |
| 无界面 | 740709 | 3.728 | 743.98 | 724／724 | 2794 |
| GUI | 740709 | 3.728 | 744.71 | 724／724 | 2796 |

实际倍率另行核对：无界面全程 Running 状态为 1 倍；GUI 先为 1 倍，在 16:07:28（仿真约 392.970 秒）首次观察到 5 倍，16:07:43（约 469.770 秒）首次观察到 10 倍。以上为 SessionStatus 首次观测时间，不冒充操作者点击时间。`g3-t05-rate-audit-20260919-161048` 保留 GUI 不符合固定 1 倍要求的 failed 子结论；原验收入口收据和两模式原始记录均未改写。用户随后明确回复“接受本轮实际变速，明确保留倍率记录”，补充收据 `g3-t05-rate-acceptance-20260919-161131` 绑定原始 SessionStatus、倍率审计、正式 result／entry-result 摘要，按该明确指示接受本轮倍率差异。**不宣称本次正式 GUI 全程固定 1 倍**，也不把该单次接受扩大为后续默认策略。原候选 GUI／无界面及正式无界面经同一审计均为全程 1 倍。

每次均关联任务 1000、分配实体 400、全部任务目标、原生末端到达、退出任务的公开状态及唯一 TaskComplete；未分配实体 500 仍持续提供真实动态状态。两次报告、全部原始格、独立复算及相同事件 GUI／无界面重放一致，重复导出和清空重放一致；漏覆盖 CSV 已保存，本轮没有漏覆盖格。每次 AMASE／UxAS 均退出 0、未强制终止，进程已回收且端口释放。

正式批次重新通过 19 项覆盖小样本、6 项真实 WaypointFollower 控制和 19 项基于本轮真实记录的完成／统计检查。任务过早完成、缺末端和错误统计等反例明确拒绝，有效零覆盖允许通过；原始分析修复前对照和所有失败收据保持。整组还验证来源／配置摘要不变、进程环境／工作目录／编码恢复及持久 PATH 不变。

复用入口如下，省略 BaselineRunId 时重新检查当前资格；不能把本次历史编号当作永远有效的来源：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3-completion.ps1 -PythonExecutable $pythonExe -Mode Headless
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-completion.tests.ps1 -PythonExecutable $pythonExe
```

功能配置固定为 `config/g3-completion.json`，复用 T03／T04 配置与证据约束，不改变原 785 秒、默认启动 1 倍或规划业务参数；实际 GUI 倍率按上文单独记录。本轮没有为覆盖效果开展算法或参数寻优。现有入口设置启动倍率并保留 SessionStatus，未禁止运行中的界面调速；后续复验必须核对真实倍率记录，不能仅凭配置宣称全程 1 倍。20 米分格下本次 724／724 是仿真结果，既不成为数值门槛，也不代表真实地形／实地覆盖保证。

T05 已完成；T06 可执行、尚未启动，T07 仍需阶段全程复验和本轮 GUI 人工确认。本次 AMASE 发布确认不能替代 T07。源码、状态、任务卡、阶段方案、总体计划和工作日志同步后，按持续授权提交、普通推送并核对远程；实际归档结果记入工作日志。
