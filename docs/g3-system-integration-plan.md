# G3 实施方案：WaterwaySearch 系统运行闭环

日期：2026-09-19，Asia/Shanghai。**G3-T01～T07 已完成，G3 已完成；G4 已细化，T01 已完成、T02 可执行。** 原规划交付不计作实现完成；T01 已另行完成实际资格复查，见 [输入基线报告](g3-input-baseline-validation.md)。当前状态见 [status](status.md)，完整任务卡见 [backlog](backlog.md#6-g3-顺序与任务卡)，过程见根级 [worklog](../worklog.md)。

## 1. 目标、输入与边界

按用户 2026-09-19 最新要求，G3 的通过条件调整为：**Windows 原生 GUI、无界面均完成 WaterwaySearch 任务执行闭环，覆盖率计算与报告正确，进程正常退出。** 当前重点是调通程序和系统，不设最低覆盖率，不为提高覆盖率进行算法／参数寻优。此前 95% 门槛及最多三组调优候选的要求取消，覆盖率提升另列后续工作。T01 报告和原始收据保留为历史快照；当前验收契约以本页及 config/g3-baseline.json 的 acceptanceRevision=2 为准，T01 历史输入资格结论保留；T02 通信修复后的 inputRevision=2 保留为历史；T05 完成／统计修复后的当前 inputRevision=3 仍为 43 项来源，已完成新发布和正式资格复查，见 [T05 报告](g3-completion-validation.md)。

- 实体 400／500 都须向 UxAS 提供真实动态状态；任务 1000 由 UxAS 实际分配的实体执行，不要求两架都被分配。完整水道的 90 个点及其顺序保持。
- 覆盖率使用 AMASE `SearchTaskAnalysis`、20 米栅格和完整任务范围，如实记录实际结果。仅为功能兼容、任务正常执行和统计正确性作必要修复／配置调整，保留原示例与差异；覆盖率高低本身不阻塞 G3。
- 本阶段包括双向协议、受控初始化、规划执行、任务完成、覆盖率、基础断线处理和整组重启；自动重连、初始化快照补齐及完整恢复矩阵归 G4。
- 浏览器控制、重置分段与场景切换归 G6；Cesium、训练、实机、真实地形校准及第二机器／离线部署不纳入本阶段。当前零高程缺省条件必须随结果披露，不能把仿真覆盖率解释为实地覆盖保证。
- 一次推进一个主要实现任务；T01 已落地独立只读资格检查，T02 已完成通信边界修复、正式发布及独立协议验收，见 [协议报告](g3-protocol-validation.md)；T03 已完成受控初始化和规划响应验收，见 [启动报告](g3-startup-validation.md)，T04 已通过两模式分段命令实际执行及内部导航／轨迹关联，见 [执行报告](g3-execution-validation.md)；T05 已完成正式两模式完整任务、可靠 TaskComplete 与覆盖统计独立复算，新 AMASE／UxAS 交接发布及当前资格通过，见 [完成报告](g3-completion-validation.md)；T06 已完成连续短程实际执行、路径／故障、残包断线清理和新编号整组恢复，见 [稳定性报告](g3-stability-validation.md)。

### 规划期输入与源码复核

| 项目 | 本轮确认及使用约束 |
| --- | --- |
| Git 与状态 | 文档实施起点 `aa0067ce53dd9b2c1ac88d2d1e59818f11240324`，工作区干净；G0～G2 已完成。实现开始时重新检查 |
| 正式产物 | 从 [G2-T07 报告](g2-uxas-release-validation.md)接收正式 UxAS、同批七模型 LMCP、既有 AMASE 与 handoff.json；规划期只读记录，T01 的实际资格结果另见下文 |
| 工具 | 规划期实际版本查询确认 Python 3.14.7、Temurin 11.0.32.1+1；构建工具及产物资格仍须通过既有解析入口复核 |
| 原始场景 | [场景 XML](../OpenUxAS/examples/02_Example_WaterwaySearch/Scenario_WaterwaySearch.xml)包含两实体配置／状态和初始巡航命令，时长 785 秒；[任务 XML](../OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/tasks/1000_LineSearch_LINE_Waterway_Deschutes.xml)为任务 1000、90 个水道点 |
| 原 UxAS 配置 | [原配置](../OpenUxAS/examples/02_Example_WaterwaySearch/cfg_WaterwaySearch.xml)会注入静态实体配置／状态，并定时发送任务与请求；这些样本不能证明实时 AMASE 状态进入 UxAS |
| 来源属性 | [TCP 桥头文件](../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkTcpBridge.h)中 `ConsiderSelfGenerated` 默认 true；[桥实现](../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkTcpBridge.cpp)会据此改写来源；[PUB 桥](../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkPublishPullBridge.cpp)只导出本地 EntityID 来源 |
| 任务完成 | [TaskServiceBase](../OpenUxAS/src/cpp/Tasks/TaskServiceBase.cpp)在实体从关联任务状态退出时发送 TaskComplete；单独出现该消息不能证明走完搜索航线 |
| 覆盖分析 | [GUI 配置](../OpenAMASE/OpenAMASE/config/amase/Plugins.xml)与[无界面配置](../OpenAMASE/OpenAMASE/config/amase_headless/Plugins.xml)均为 20 米；[SearchTaskAnalysis](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/SearchTaskAnalysis.java)按已见／总栅格计算并格式化百分比；[AnalysisManager](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/AnalysisManager.java)分析路径创建进度窗口，无界面导出须实际验证并隔离窗口依赖 |
| 既有验收限制 | [G1 探针](../tests/amase/RuntimeProbe.java)在 GUI 20 秒暂停，[G1 编排](../scripts/amase/amase.py)限制无界面运行 120 秒；G3 新建独立编排与插件，保留原验收含义 |

上述表格保留规划期的历史记录与源码确认，不是双向运行、任务完成或覆盖率通过的证据。T01 已完成 `g3-t01-check-20260919-093348-422` 实际资格复查并冻结 35 个输入，详见 [报告及八项风险](g3-input-baseline-validation.md)。T01 当时发现原任务 AllAny 在线搜索覆盖分支中提前返回；T05 已保留原参数，以最小样本、原记录重放和两模式正式全程验证统计修复，见 [完成报告](g3-completion-validation.md)，未以调参绕过错误；重复 ViewAngleList／旧相机字段须核实有效值。CMASI 请求／响应没有关联 ID，T04 通过 Unique 请求／响应、分配与航点内容关联。T01 当时未作业务修复；T02 的通信修复与字段实测另见 [协议报告](g3-protocol-validation.md)。G1 实际接收和 G2 内部消息分别见 [TCP 报告](g1-tcp-validation.md)、[HelloWorld 报告](g2-uxas-helloworld-validation.md)。

## 2. 已确定的技术路线

### 连接、来源与端口

主链路采用 **AMASE TCP ↔ UxAS 现有 TCP 桥**。优先对现有桥作最小兼容修复；若必须另建协议适配拓扑，保留最小复现后调整方案，不同时启用两条等价主链路。

UxAS TCP 观察口用于读取总线消息、注入验收任务／请求以及正常停止请求。观察客户端只发送明确的编排消息，不转发所收业务消息；任务和规划请求各有单次触发记录，实际 MissionCommand 由 UxAS 生成。观察记录与 AMASE 内部事件、真实收发样本交叉核对。T03 的控制观察桥显式 ConsiderSelfGenerated=true，把客户端 900／1 的编排输入登记为本地桥来源，任务才能经主桥导出；AMASE 主桥仍为 false。观察桥过滤自身导入消息，改写证据由 UxAS 原消息日志见证；详情见 [来源矩阵](g3-startup-validation.md#2-受控顺序与消息来源)。

| 模式 | AMASE 主 TCP | 实体 400／500 TCP | UxAS TCP 观察口 |
| --- | --- | --- | --- |
| GUI | 5555 | 9400／9500 | 9999 |
| 无界面 | 5556 | 19400／19500 | 9999 |

两模式顺序运行。端口是可配置的示例默认值，启动前检查冲突，启动后核对 PID，退出后检查释放；不得静默换端口或结束无关进程。PUB／PULL 若为来源对照试验启用，5560／5561 也必须登记和检查，正式闭环不依赖 PUB 提供完整状态。

AMASE 对应的 UxAS TCP 桥显式使用 `ConsiderSelfGenerated="false"` 保留接收来源。T02 已完成正式 true／false 对照；主桥另开启 `ExportOnlyLocalMessages="true"` 防止原巡航命令回送。记录外层来源、接入连接、进入总线后的属性及 PUB 导出结果；业务实体 ID 与消息源 EntityID 分开记录，不从单一属性推断消息真实来路。

### 初始化与生命周期

在 G3 独立运行副本中取消 `SendMessagesService` 的静态实体配置／状态注入和定时任务触发，原 XML 保留。由编排按以下顺序推进：

1. 复查工具、正式产物、同批消息库、配置和全部端口。
2. AMASE 初始化并保持暂停；G3 插件控制首次启动，避免无界面 `ConstructiveControl` 抢先开跑。
3. 启动 UxAS，确认主链路及观察连接就绪；监听存在、连接建立、消息解析及初始数据完整分别记录。
4. 启动仿真；确认 400／500 的配置和多条时间递增、位置变化的真实状态进入 UxAS。缺失数据按超时失败，不用静态文件补齐。
5. 单次发送任务 1000，等待 TaskInitialized，再单次发送原 AutomationRequest 内容；绑定实际产生的请求／响应身份和本次运行编号。
6. 采集规划、命令、实际执行和覆盖证据；完成后保存分析结果，正常关闭本次进程。初始化所需的本地暂停屏障由 G3 插件实现，不据此宣称已有通用远程控制接口。

默认 GUI／无界面均使用 1 倍速。原始场景先按 785 仿真秒运行；为完成任务执行而必要调整的副本最多 1800 仿真秒；不因覆盖率低延长运行。初始化阶段、任务初始化／规划等待及正常关闭各设 30 秒超时，整次自动运行墙钟上限 2700 秒。GUI 自动运行到验收观察点后可进入独立的人工确认等待状态，等待人工不算仿真运行或自动成功；确认后仍须验证正常退出。任何超时、强制终止或未完成条件都保留失败／待确认状态。

T05 本轮正式无界面实际全程 1 倍，GUI 运行中实际变为 1→5→10 倍；用户明确接受本轮实际变速并要求保留倍率记录，见 [T05 报告](g3-completion-validation.md#5-正式发布资格与两模式验收)。该单次接受不改变默认启动 1 倍，不冒称本次正式 GUI 全程固定 1 倍；后续复验必须核对真实 SessionStatus，不能仅依据启动参数判断实际倍率。

G3 插件只承担本地编排、事件观测、分析导出和关闭。仿真毫秒与墙钟时间分别保存，TaskActive／TaskComplete 时间须追踪实际时间源，不能仅依据字段注释转换为 UTC。

### 任务完成与覆盖率计算正确性

完整执行链必须关联同一任务和实际执行实体：`TaskActive → 实际任务航段推进 → 末端航段完成 → TaskComplete`。同时核对 UxAS 原始计划、分段 MissionCommand、AMASE 接收事件、CurrentCommand／CurrentWaypoint／AssociatedTasks 和轨迹。原配置的航点分段及重叠行为保留，正常续传与重复执行分开判断；初始巡航命令不能充作规划命令证据。

覆盖率复用 AMASE 栅格与传感器判定模型，无界面导出隔离进度窗口，保存原始计数、漏覆盖位置及分析 XML。完整任务统计要求 `total > 0`、`0 ≤ seen ≤ total`，实际覆盖率为 `100 × seen / total`，报告按既定精度格式化后应一致；这些数值约束不能单独证明计算正确。还须通过已知覆盖／未覆盖、重复观测不重复计数、波段匹配与 AllAny、可人工复核的小样本，以及同一事件记录在两模式下计算一致的对照。实际两次运行分别留存数据，不要求不同轨迹产生相同百分比，不合并运行。

先记录原参数及原始分析行为，修复必要的兼容或统计缺陷，再固定 GUI／无界面共同使用的功能验证配置。完整水道、实体身份与 20 米栅格保持；每次必要修复保存依据、配置／源码差异及复验结果。低覆盖率仅作为后续算法／参数实验的基线，不触发 G3 的搜索调优循环。

允许修复经对照证明的覆盖统计实现缺陷，但不得为提高数值而放宽传感器条件、删除未覆盖水道或改变分母。T05 已核实并修复 AllAny 提前返回、20 米分格和分析导出问题，最小样本／同记录对照、新 AMASE 重建／复验及正式发布均通过，失败证据保留。计算错误、缺末端执行、正常退出失败或任务执行超过时长上限仍阻塞相应任务；经验证正确的低覆盖率不阻塞。

现有 [AnalysisManager](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/AnalysisManager.java)按事件记录计算报告，[SearchTaskAnalysis](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/analysis/SearchTaskAnalysis.java)统计栅格；[线搜索规划服务](../OpenUxAS/src/cpp/Tasks/CmasiLineSearchTaskService.cpp)根据任务及实体约束构造规划选项。现有 WaterwaySearch 链路没有“报告覆盖率 → 自动修改算法／参数 → 重新仿真直至达标”的反馈流程。UxAS 内置分配／规划算法的求解能力不能视为这种自动调优能力。

## 3. 任务顺序与交付

| 任务 | 前置 | 独立交付 | 通过依据 |
| --- | --- | --- | --- |
| G3-T01 输入与验收基线 | G2 完成 | 产物／场景清单、消息流、验收判据 | 正式来源可追溯，真实状态与注入样本、巡航与规划命令明确区分 |
| G3-T02 双向协议与来源验证 | T01 | 双向样本、严格解析与来源矩阵、必要最小修复 | Java／C++ 真实两端兼容，半包／粘包及过滤对照通过，无转发回路 |
| G3-T03 受控启动与初始化 | T02 | 独立 Windows 编排与 AMASE 插件 | 初始数据完整后触发任务／请求，正常关闭且无端口残留 |
| G3-T04 规划命令实际执行 | T03 | 请求到实际执行的关联报告 | 命令、航点、任务关联与真实轨迹一致 |
| G3-T05 任务完成与覆盖统计正确性 | T04 | 完成判定、正确性对照、分析导出与必要修复报告 | GUI／无界面各自完成任务，统计与报告正确，冻结功能验证配置 |
| G3-T06 稳定性与故障复验 | T05 | 重复／路径／故障矩阵及整组重启证据 | 三次短程闭环正常启停，故障明确失败，重启不混入旧运行 |
| G3-T07 阶段验收与 G4 交接 | T06 | 最终两模式全程复验、人工确认、唯一配置及交接清单 | 完整执行、覆盖统计正确性及正常退出通过，才登记 G3 完成 |

任务状态、修改范围、实施步骤、证据、回退与停止条件详见 [七张任务卡](backlog.md#6-g3-顺序与任务卡)。

## 4. 接口现状与来源管理

以下是运行、验收及 GUI 收尾的接口约定，**T03 的运行、自动验收及 GUI 正常收尾入口已验证，见 [启动报告](g3-startup-validation.md)；T02 协议入口见 [报告](g3-protocol-validation.md)**。T01 的独立输入资格命令已通过，见 [基线报告](g3-input-baseline-validation.md#1-本轮交付与复用入口)：

- 已提供 run-g3.ps1、g3-startup.tests.ps1、finish-g3-gui.ps1。运行输入包含模式、配置、明确 Python 路径和运行编号；收尾绑定运行编号。当前 scope=startup、仅消费合格正式包，1 倍速且保留原 785 秒场景；取得非空规划响应即收尾。T04 另提供 run-g3-execution.ps1／g3-execution.tests.ps1 和 config/g3-execution.json，实际命令与局部任务航段已通过；T05 另提供 run-g3-completion.ps1／g3-completion.tests.ps1 和 config/g3-completion.json，已通过正式完整执行与统计正确性对照；T06 提供 run-g3-stability.ps1／g3-stability.tests.ps1、config/g3-stability.json，绑定合格 CompletionRunId，独立运行与故障矩阵已通过；不能把短程入口用于阶段完成声明。
- 当前输出包含运行状态、来源、配置快照、消息与事件及进程退出证据；完整任务及覆盖统计已由 T05 验证，稳定性／故障已由 T06 验证，T07 最终两模式实际 1 倍全程及本轮 GUI 人工确认／正常退出已通过；int64 实体／任务／命令 ID 用十进制字符串。人工确认只对本次运行有效，不能复用 G1 的历史确认。
- 编排优先使用已验证的 Python 标准库和消息代码，协议解析复用 [G1 严格解析器](../scripts/validation/sentinel.py)的规则；扩展时单独登记输入，避免无意改变旧构建来源。不能将 Python 原始 LMCP 直接当作完整 Java／C++ TCP 帧。
- G3 编排／插件位于 scripts/g3_integration，测试位于 tests/g3_integration，默认配置为 config/g3-startup.json；具体已验证命令见 T03 报告。现有 G1／G2 接口及原示例保留，MDM／生成代码不因编排而改变。
- 每次运行使用独立 `out/runs/<run-id>/`；编译插件等候选放在独立 `out/build/`。正式产物通过既有资格解析入口消费，不直接读指针后绕过来源检查。
- 若业务源码、构建输入或消息生成输入改变，按影响重新构建、验收及发布，必要时复验相应 G1／G2 链路；不修改旧来源清单使旧包继续“通过”。仅配置／编排改变也须独立记录哈希并重新验收受影响的 G3 任务。

T07 已提供 run-g3-acceptance.ps1／g3-acceptance.tests.ps1／finish-g3-acceptance.ps1 和 config/g3-acceptance.json，绑定合格 StabilityRunId。最终两模式、当前 GUI 确认及正常退出通过后输出 acceptance／handoff；完整命令、批次和结果见 [阶段报告](g3-stage-validation.md)，唯一配置及后续边界见 [G4 交接](g3-g4-handoff.md)。

## 5. 验收矩阵与证据

| 层次 | 必须覆盖 | 判定边界 |
| --- | --- | --- |
| 协议 | 双向真实帧、半包／粘包、非法长度、坏校验和、来源保留／改写、PUB 过滤、重复转发、断线残包 | 验收器坏帧拒绝与真实后端拒绝分别留证；模拟样本不能替代实际两端收发 |
| 初始化 | 端口归属、连接和解析就绪、两实体配置与动态状态、任务初始化后请求、缺数据及提前请求反例 | 固定延时、静态注入或观察口连接成功不能代替就绪条件 |
| 实际执行 | 请求／响应、计划与分段命令、AMASE 接收、当前命令／航点／任务关联、轨迹与末端 | 发送成功、收到命令、窗口出现航线、原巡航运动均不能单独判成功 |
| 完成与覆盖 | 提前 TaskComplete、错误实体／任务、缺末端、空栅格、已知覆盖与去重／波段对照、计数及报告一致性、两模式全程 | 每次运行满足完成链，统计正确且结果如实保存；没有最低覆盖率要求 |
| 生命周期 | 连续三次短程闭环、其他工作目录、中文空格路径、缺失／不符来源、端口冲突、提前退出、超时 | 正常退出码 0、无强制终止、所属进程回收及端口释放；短程不替代全程搜索 |
| 基础恢复 | 受控断开、残包清理、标记当前运行失败、整组停止后新编号启动 | 新运行不能消费旧帧、旧任务或旧完成证据；在线自动重连及快照补齐归 G4 |
| 最终复验 | 冻结合格配置下 GUI／无界面各一次全程、本轮 GUI 人工确认、正常退出 | 同一业务配置；全部通过后才完成 G3 |

原始字节及帧范围、解码消息、AMASE 事件、UxAS 日志、分析结果、配置差异、源码／工具／产物哈希、命令、工作目录、PID、退出码和失败诊断绑定同一运行编号。报告保留关键结论与可复现命令，原始运行物受忽略规则覆盖。

## 6. 停止、回退与阶段收尾

- 来源不一致、双向兼容未解决、真实初始化缺失、无法证明实际执行、任务未完成、覆盖统计错误或正常退出失败时，不推进依赖这些结果的任务。必要兼容修复在当前任务范围内进行，失败记录保留。
- 回退只处理本任务修改、配置副本和持有句柄的进程；保留原场景、合格包、旧指针及历史验收报告。不卸载共享工具、不清空全局缓存、不以宽泛进程名清理实例。
- 每项任务先验收，再追加工作日志、同步状态与待办，按持续授权提交、普通推送并核对远程。文档细化当时只登记“G3 已细化，实施尚未启动”；当前 T01～T07 已按完整证据与本轮人工确认登记 G3 完成，不由任何单卡结果代替阶段验收。
- T07 交接唯一合格连接配置、同批产物身份、消息方向与来源／过滤矩阵、初始数据清单、实际时间语义、协议样本、完整任务与覆盖报告、正常退出证据及 G4 恢复缺口；不能把观察客户端描述为已建成的网关。
- 七卡与 [G3 结束检查](backlog.md#7-g3-阶段结束检查)全部通过后才登记 G3 完成。自动重连／快照补齐归 G4，重置分段归 G6，其余延期项保持原归属。
