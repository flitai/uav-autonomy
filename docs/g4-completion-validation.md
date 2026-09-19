# G4-T06 两实体完整任务验收

日期：2026-09-20，Asia/Shanghai。**G4-T06 已完成。** 前置 [T05](g4-recovery-validation.md) 已通过并以 `a206fe56762ec5e7fe2159c84ff7d61577aa1102` 提交、推送及核对远程。

## 范围与入口

原 WaterwaySearch 两实体 400／500、完整水道、任务 1000、实际 1 倍、785 秒原时长和 20 米栅格保持。运行顺序为 Headless、Gui；每模式均要求真实规划、内部执行、可靠完成、覆盖独立对照和正常退出。保留两个实体及完成后的任务对象，不注入删除操作。

编排在 `scripts/g4_completion/runtime.py`，策略在 `config/g4-completion.json`，复查 T05 合格收据及其全部来源，并复用原 G3 完成／统计探针。网关和运行编排独立，三个持续客户端分别正常消费、刷新和慢消费。任务执行中验证半帧观察断线、整个网关重启和跨 TaskComplete 的双观察缺口，末端用独立 Edge 页面检查真实场景、刷新及正常关闭。

```powershell
# 仓库根目录；使用已核查的 Python 3.14.7 x64。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g4-completion.tests.ps1 -PythonExecutable $pythonExe
# 双模式完成后，用本次编号执行独立的只读审计，另存收据。
& $pythonExe -I -B -X utf8 .\scripts\g4_completion\audit.py --root (Get-Location).Path --run-id '<G4_T06_RUN_ID>'
```

单模式入口为 `scripts/windows/run-g4-completion.ps1`，接受 Mode 和可选 BaselineRunId；没有提供基线时重新核查正式来源。全部场景副本、原始接收、日志、快照、浏览器证据和收尾记录放入本次新的 `out/runs/g4-t06-*`。

## 实际验证

主验收 `g4-t06-test-20260920-010936-703` 的 result／entry-result 和两案例均 passed，退出码 0；57 项实现来源及 43 项 G3 冻结输入未变。当前正式 AMASE／UxAS 和同批 LMCP 保持 T05 身份。本卡只增加运行编排、配置与验收，没有改业务源码、算法、飞行参数或原场景。

独立审计 `g4-t06-audit-20260920-013549-190195` passed、退出 0。审计脚本在主运行结束后新增，绑定自己的 SHA256、父收据及原始证据；没有改写父运行或将后加脚本写入旧来源清单。复用本卡时同时核查两份收据；审计逐项核查 57 项来源以及 Headless 495／Gui 496 项证据摘要，并拒绝倍率为 2 和缺少运行时钟的样本。

| 项目 | Headless | Gui |
| --- | --- | --- |
| 实际 Running 时钟 | 1405 条，全部倍率 1 | 1405 条，全部倍率 1 |
| 同身份 TaskComplete | 任务 1000、实体 400、740709 ms | 任务 1000、实体 400、740709 ms |
| 网关原始完成帧／持久完成事件 | 0／1 | 0／1 |
| 20 米覆盖计数 | 724／724 | 724／724 |
| 独立复算实体状态数 | 2794 | 2792 |
| 持续客户端增量数（正常／刷新／慢消费） | 5011／4833／4449 | 5014／4836／4448 |
| 每客户端经历的发布流 | 4 | 4 |

内部导航、实际任务航段、末端到达、完成身份与时间、命令交接取证以及 Java 两模式分析重放均通过。实际完成由分配给任务的实体 400 产生，实体 500 保持原有飞行；两个实体和已完成任务都保留在最后快照中。覆盖百分比是本轮结果，没有设置最低值。GUI／无界面采样数可因收尾时间稍异，各自都从同一批原始分析事件独立复算，并未拿一轮计数替代另一轮。

两模式在 700 仿真秒后切断两条观察连接，跨过真实完成再恢复；当时后端主链路持续执行，网关保留恢复状态。原始网关收包中没有 TaskComplete，当前日志按持久身份只产生一个完成事件，恢复快照的身份、时间与后端证明一致。半帧尾部另存，未宣称原始字节已补齐。运行中完整重启网关，三个客户端重新获取新快照后继续有序增量；各模式最终三个客户端状态摘要相同。

Edge 153.0.4234.32 两模式均实际渲染、刷新、正常关闭，JavaScript 异常 0；已查看两张 diagnostic.png，核对两个实体、任务 1000、分配 400、完成时间和倍率。AMASE／UxAS、各网关实例、客户端及验收 Edge 全部正常退出，无强制终止；11 个声明监听端口均已释放。每模式任务与请求各注入一次，网关业务控制帧为 0。

证据位于本次 `out/runs/<运行编号>/{headless,gui}/`：case-result.json、原始收包和 amase／uxas.jsonl、amase 内部导航与分析记录、gateway-host 各实例及 normalized-events.db3、completed-full-scene.json、continuous-clients、edge-browser。原始数据按仓库规则保留在被忽略的 out，不提交 Git。

G4 阶段人工 GUI 确认属于 T09，本卡的 Edge 自动化和后端 GUI 自动运行不能代替真实人工确认。覆盖率只作统计结果，不设最低值；零地形、ASCII 业务字段、无 Cesium 和无浏览器控制等边界保持。
