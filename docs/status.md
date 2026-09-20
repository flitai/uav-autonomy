# 项目实施状态

更新日期：2026-09-20。依据：[总体实施计划](../04.项目总体实施计划与阶段验收.md)、[G0 报告](g0-baseline.md)、[Java 环境验收](g1-java-validation.md)、[T03 消息库验收](g1-lmcp-validation.md)、[T04 AMASE 验收](g1-amase-validation.md)、[T05 TCP 验收](g1-tcp-validation.md)、[G2 实施方案](g2-windows-uxas-plan.md)、[G3 实施方案](g3-system-integration-plan.md)、[任务清单](backlog.md)。过程记录见根级 [worklog.md](../worklog.md)。

## 当前关卡

**G0～G4 已完成；G4-T01～T09 验收通过，正式网关及日常入口已发布。G5-T01～T03 已完成；本地矢量、USGS 区域地形和在线影像通过地图资源验收，T04 可执行，真实地形后端任务与业务显示待后续。** G5 见 [实施方案](g5-cesium-display-plan.md) 和 [十一张任务卡](backlog.md#9-g5-顺序与任务卡)。G4 方案见 [实施方案](g4-message-gateway-plan.md)；规划提交 `908fdfd` 已推送并核对远程。原生 UxAS 历史正式发布见 [T07 报告](g2-uxas-release-validation.md)。

| 项目 | 当前记录 |
| --- | --- |
| 最近完成的规划 | [G5 方案](g5-cesium-display-plan.md) 已按 T01～T03 证据及后续决定修订：USGS 主源／Copernicus 对照、WGS84 高度链、区域外参考椭球、DTED 调用限制、模型转换及真实接入／资源回归；本次仅更新文档 |
| 最近通过的实现任务 | G5-T03 本地矢量、USGS 区域地形、Esri 影像、Range／代理、两类路径及各十组验收；[报告](g5-map-validation.md) |
| 三维模型输入 | 用户提供 16 个 OSGB 原件，约 154.1 MB，文件摘要已登记；转换及显示校准归 G5-T06，见 [输入登记](g5-model-inputs.md) |
| 当前执行结果 | G5-T03 已完成；普通构建 g5-t03-build-20260920-184439-778／验收 g5-t03-test-20260920-184747-248，中文构建 g5-t03-build-20260920-184747-244／验收 g5-t03-test-20260920-185000-639 均 passed；未切换正式前端指针 |
| G3 历史基线 | T07 起点 `6c0294e3`，当时工作区干净；新增独立阶段验收，业务源码／XML／生成代码及 T03～T06 实现保持。inputRevision=3、43 项冻结输入复查通过 |
| 已归档历史 | G1-T01～T03 为 `304def9`，G1-T04 为 `f2f73ab`，G1-T05 为 `d77dd78`；T04 `b8ccf72`／`68ed420`、T05 `0fe8553`／交接 `5c2d387` 已推送 origin/main |
| 本轮变更 | G4 方案 `908fdfd`、T01 `ca21032`、T02 `22cacc6` 已归档；T03 `71c5906` 已归档并发布日志修复；T04 `f3b4d08` 已归档；T05 `a206fe5` 已归档；T06 `g4-t06-test-20260920-010936-703` 两模式全程及独立审计通过 |
| 当前正式批次 | AMASE g1-t04-build-20260920-024628-136806，Finalize g1-t04-finalize-20260920-080752-574040；UxAS 构建 g2-t05-build-20260920-082330-977，发布 g2-t07-publish-20260920-083245-918；LMCP 不变 |
| 正式网关与入口 | g4-t09-publish-20260920-115418-723744；入口资格 g4-t09-release-check-20260920-115528-388842；使用 start-g4-session.ps1，见 [G5 交接](g4-g5-handoff.md) |
| 已确定的 G2 路线 | MSVC v143＋CMake 3.31、Release x64／动态 CRT；固定 vcpkg baseline／overlay；Zyre／串口关闭，CZMQ／TCP 保留 |
| 已验证工具 | Temurin 11.0.32.1+1、Ant 1.10.18、Python 3.14.7 x64；Build Tools 17.14.41／cl 19.44.35229、SDK 工具 10.0.26100.7705、CMake 3.31.12、Ninja 1.13.2、固定 vcpkg 提交及工具；Node 24.21.0／npm 11.19.0、独立 Rasterio／GDAL 与 PyProj／PROJ，见 [G5-T01](g5-environment-validation.md) |
| 已验证能力 | G0～G4；真实规划／执行／完成，20 米统计，严格协议、状态／持久记录、HTTP／WS、两路观察和网关恢复，20 实体两模式各 30 分钟及三客户端；当前 GUI 确认与正常退出 |
| 尚未完成验收 | G5 Cesium 与同源真实地形；G6 控制／重置分段；G7 正式回放；G8 第二机器与离线部署 |
| 下一动作 | G5-T04：先审计 DTED 负值／十倍间距元数据对实际调用的影响，冻结独立场景及高度适配，再验证地形参与飞行、传感器、三类小规模任务和 20 米统计 |
| 当前边界 | G4 已发布；G5 用原矢量＋USGS 区域主地形，Copernicus 只作对照，旧 Terrarium 归档；西经 122～120／北纬 45～46 度外仅按未验收参考椭球浏览。无覆盖率／FPS 硬门槛，不开展寻优 |
| 本轮实际倍率 | G4-T08 两模式各 3385 条 Running SessionStatus 均为 1.0，均到 1800009 ms；历史变速取证保持原记录 |
| 已确定的 G3 验收 | GUI／无界面分别完成任务执行，AMASE 20 米栅格覆盖计算与报告正确，本轮 GUI 确认及正常退出；不设最低覆盖率，算法／参数寻优归后续 |

G4-T03 已修复 UxAS 日志并发读写缺陷并正式发布；旧失败运行保留。新资格 g3-t01-check-20260919-233710-372、Web 环境复验、32 项状态／记录检查及两模式各 54 批在线只读消费通过，关键日志完整、正常退出。来源修订在 config/g4-baseline.json，保留 G3 历史 handoff，详见 [T03 报告](g4-state-validation.md)及工作日志 WL-20260919-014。

G4-T07 正式资格已完成：新 AMASE 的 19 项并发、31 项统计、原线分析回归、11 组自动验收，以及四场景全程／独立审计均通过。本轮用户确认后 GUI 正常退出并正式发布，UxAS AMASE 交接复验发布通过；inputRevision=4、45 项冻结输入，新资格 g3-t01-check-20260920-081222-593、Web 环境复验及正式组合收据 g4-t07-qualified-20260920-081353-913195 passed。正式文件与候选取证字节相同，来源链十项反例被拒绝；旧结果保留。见 [T07 报告](g4-mixed-validation.md)。T08 后续已完成，见 [稳定性报告](g4-scale-validation.md)；T09 后续已通过并发布，见 [阶段报告](g4-stage-validation.md)。

## 已处理项与剩余缺口

| 项目 | 当前结论 | 下一次最小验证 | 归属 |
| --- | --- | --- | --- |
| Java／javac／Ant（R02 的 Java 部分） | 已构建 LmcpGen、统一消息库和 AMASE，固定版本在项目 .tools 下 | 后续复用受控环境，无需重新下载 | 后续复用 |
| 生成物管理（R07） | AMASE 构建、运行和配置副本均隔离；已成套发布，退出和端口释放通过 | 后续启动继续核对来源清单与端口 | 后续复用 |
| Java 源码与依赖兼容性 | AMASE 保持 source／target 11；统一消息库保留 Java 8 字节码，指定场景通过 | 新场景按任务验证；不宣称已在 JDK 8 运行 | 后续任务 |
| 生成器 CLI 诊断 | T02 检查诊断，T03 还检查输出文件、编译、类型清单与双向样本 | 后续保持输入／输出及版本校验 | 后续复用 |
| 消息库一致性及 Python（R03／R09） | 完整 AMASE 编译及指定场景的真实 TCP 状态使用新库通过；UXTASK 7→8 的兼容差异仍成立 | 其他场景的动态使用、双向命令按任务检查 | G3／后续场景 |
| GUI 重置与验收区间 | 人工重置触发既有全程时间单调检查，原 failed 记录保留；同版本受控复验与正常退出通过 | 重置及场景切换按不同时间段建立验收，不沿用全程单调假设 | G6 |
| AMASE 路径与地形（R06／R08） | 两类路径通过；G4 零高程基线保留，G5-T02 USGS 区域派生与两类查询、T03 地图资源通过 | T04 审计 DTED 负值／间距实际调用，独立验证真实地形飞行、传感器和 20 米统计，禁止缺地形时静默使用零高程 | G5-T04 |
| AMASE 与 UxAS 封装（R04） | T02 正式真实双向 Sentinel／属性／LMCP、分包、来源和正常关闭通过 | G3 核查双向封装、来源过滤、完整执行／覆盖及基础断线处理；自动重连／快照补齐归 G4 | G3／G4 |
| C++／Node 与旧依赖补丁（R02／R10） | T01 工具链、T02 固定依赖及 T03 七模型 LMCP 通过，生成器／模型未变；微软目录描述哈希差异原因仍未知，实体已有独立签名验证；Node 24.21.0 及最小 Cesium 构建已由 G5-T01 验证 | G2 构建、HelloWorld 和正式发布已通过；既有转换、符号性及弃用警告保留，其他服务按 G3 场景验证 | G2／G5 |

T01 另确认：原任务 AllAny 在现有覆盖分析分支中直接返回，归 T05 语义核实、统计正确性对照及必要最小修复，不以调参绕过错误；重复 ViewAngleList／旧相机字段归 T02／T05，CMASI 请求无关联 ID，T04 已通过 Unique 身份、分配及分段／轨迹关联。详见 [八项 G3 风险](g3-input-baseline-validation.md#6-已确认风险与后续责任)，该段描述 T01 历史发现；T05 已修复并完成候选实测，两模式均为 724／724，独立复算一致，见 [T05 报告](g3-completion-validation.md)。

T03 新登记：旧 LMCP 字符串长度与 UTF-8 字节长度存在差异，当前使用 ASCII 编排标识和相对场景路径；中文运行目录已通过，不代表任意 Unicode 消息字段已支持。后续 G4／G6 涉及中文消息时须按生成器／模板来源链修复和复验。

上游精确 SHA 未知（R01）、Anod 来源绑定（R05）继续按 [G0 风险表](g0-baseline.md#6-风险归属与下一次验证)执行。G0 保留为历史快照，本页反映当前进度。

## 当前使用约定

- 用户已持续授权阶段性工作确认完成并通过验收后自动提交、推送，无需逐次确认；先同步日志与状态，核对提交范围和远程结果。完整规则见 [AGENTS 第 7 节](../AGENTS.md#7-修改规范)。
- Java 工具通过固定清单与项目内脚本使用，安装目录和下载缓存位于被忽略的 `.tools/`；不修改持久环境变量或执行策略。
- C++ 工具通过 `setup-cpp.ps1` 准备、`use-cpp.ps1` 在当前进程启用，完整验收为 `tests/windows/cpp-toolchain.tests.ps1`；命令及实际版本见 [T01 记录](g2-cpp-toolchain-validation.md#63-完整验收结果与复用命令)。MSVC／SDK 使用微软系统默认目录，便携工具与缓存位于 `.tools/`。
- 第三方依赖通过 `build-deps.ps1 [-Rebuild]` 生成候选，`deps.tests.ps1 -BuildRunId <编号>` 验收并发布；复用时调用 `Resolve-DepsPackage` 核对合格指针、来源和完整性，再消费 `UxasDependencies` 目标。具体版本、已知兼容细节及证据见 [T02 记录](g2-dependencies-validation.md)。
- Java／C++／Python 消息已由同一组 `OpenUxAS/mdms/` 快照生成，模型身份与哈希锁定在 `config/lmcp-models.json`，输出为 `out/generated/lmcp/{java,cpp,py}/`；C++ 库由 `build-lmcp-cpp.ps1` 构建、`lmcp-cpp.tests.ps1` 验收发布。后续通过 `Resolve-LmcpCppPackage` 检查实时来源后消费 `UxasLmcp`／`Uxas::lmcp`，详见 [T03 记录](g2-lmcp-cpp-validation.md)。
- LmcpGen 通过 `scripts/windows/build-lmcpgen.ps1` 构建；正式产物为 `out/artifacts/lmcpgen/LmcpGen.jar`，同目录 build-info.json 记录输入、工具与验收。每次中间物放在 `out/build/lmcpgen/<run-id>/`，失败不替换已有合格产物；其他组件沿用 build.dir／dist.dir／dist.jar 覆盖约定。
- 消息通过 `scripts/windows/generate-lmcp.ps1 -PythonExecutable <实际解释器路径>` 生成与验证；正式 Java 库为 `out/artifacts/lmcp/java/lmcplib.jar`。使用前核对生成目录 generation-info.json 与产物目录 build-info.json 的运行编号、模型及文件哈希。旧随库 JAR 保留，不允许同一 classpath 混入新旧版本。
- AMASE 通过 build-amase.ps1 构建候选，完成验收后正式发布到 `out/artifacts/amase/`；run-amase.ps1 默认使用正式目录，配置与资源隔离到本次运行目录。标准命令和显式端口参数见 T04 报告。
- 实际 TCP 接收通过 receive-amase.ps1 指定本次 AmaseRunId；amase-tcp.tests.ps1 自动运行两种模式、分包／故障及路径验收，Finalize 需要本轮真实 GUI 人工确认。客户端仅接收不发送；来源、数据与统计保存在独立 out/runs 目录，标准命令见 T05 报告。
- G3-T01 输入资格入口为 `scripts/windows/check-g3-baseline.ps1 -PythonExecutable <实际解释器路径>`，使用新 PowerShell 进程及项目既有 Bypass 方式调用；原例语义反例为 `tests/g3_baseline/checks.py`，具体命令见 [T01 报告](g3-input-baseline-validation.md#1-本轮交付与复用入口)。此入口不启动仿真，不代表双向网络通过。
- G3 启动使用 run-g3.ps1，自动验收使用 g3-startup.tests.ps1；GUI 可在规划后暂停并用 finish-g3-gui.ps1 正常收尾。当前只验收 startup，完整命令与来源见 [T03 报告](g3-startup-validation.md)。
- G3 实际执行使用 run-g3-execution.ps1／g3-execution.tests.ps1，配置为 config/g3-execution.json；详见 [T04 报告](g3-execution-validation.md)。原 TurnShort 与四点分段重叠已登记，未改业务参数。
- G3 完整任务使用 run-g3-completion.ps1／g3-completion.tests.ps1，配置为 config/g3-completion.json；详见 [T05 报告](g3-completion-validation.md)。同坐标任务末端标记的到达判定已作功能修复，普通 TurnShort 和规划参数保持；独立检查覆盖完成链、原始统计与逐格重放。
- G3 稳定性使用 run-g3-stability.ps1／g3-stability.tests.ps1，配置为 config/g3-stability.json，要求明确的合格 CompletionRunId；实际倍率、独立运行身份、故障 failed 与上层预期拒绝分开，见 [T06 报告](g3-stability-validation.md)。
- 运行记录与临时探针分别位于 `out/runs/`、`out/tmp/`，不进入 Git。隔离故障副本不能充当正式工具。
- 各任务独立验收并追加根级工作日志；G1 已依据 T01～T05 的历史证据登记完成，不据此宣布原系统闭环通过。G2-T01～T07 已通过并登记 G2 完成；HelloWorld 内部消息不代表 AMASE↔UxAS 双向网络通过。
- G2 按 [阶段方案](g2-windows-uxas-plan.md)和七张任务卡推进。工具准备、依赖、LMCP 及 UxAS CMake 配置入口已验证；用 `configure-uxas.ps1` 和 `uxas-cmake.tests.ps1` 复核构建图，详见 [T04 报告](g2-uxas-cmake-validation.md)。完整构建与候选验收入口 `build-uxas.ps1`／`uxas-build.tests.ps1` 已通过，候选由构建／验收双编号解析；运行入口 run-uxas.ps1 和验收入口 uxas-helloworld.tests.ps1 已通过；最新候选双编号与正式包见 [T02 报告](g3-protocol-validation.md)，G2 历史身份见 [T07 报告](g2-uxas-release-validation.md)，T05／T06 报告保留历史批次。正式运行使用 run-uxas-release.ps1，脚本消费使用 Resolve-UxasPackage；复验和发布使用 uxas-release.tests.ps1／publish-uxas.ps1。

- G3 阶段验收使用 run-g3-acceptance.ps1／g3-acceptance.tests.ps1，绑定合格 StabilityRunId；GUI 完成后等待当前用户确认，使用 finish-g3-acceptance.ps1 正常收尾。四份配置与来源由本次 handoff 摘要绑定，详见 [T07 报告](g3-stage-validation.md)。

## 下一次工作的起点

先读按后续讨论修订的 [G5 实施方案](g5-cesium-display-plan.md)、[十一张任务卡](backlog.md#9-g5-顺序与任务卡)、[地理检查报告](g5-geography-validation.md)、[地图报告](g5-map-validation.md) 和工作日志 WL-20260920-014～017。T01～T03 已完成，T04 可执行，T05～T11 待前置。原始 DEM 异常及失败收据保留；USGS 主源／Copernicus 对照、WGS84 同源正高／椭球高派生及地图资源已经独立验收。下一步审计 DTED 实际调用并完成真实地形小规模任务与统计；模型接入归 T06。本轮方案修订仅改文档，G3／G4 历史基线和 T03 地图就绪均不代表 G5 整阶段已验收。

G3 已完成，最终资格 `g3-t01-check-20260919-172312-180`、阶段验收 `g3-t07-test-20260919-173116-474` 及本轮 GUI 确认／正常退出已通过。先读 [T07 报告](g3-stage-validation.md)、[G4 交接](g3-g4-handoff.md) 与工作日志 WL-20260919-010。唯一连接配置为 config/g3-startup.json；execution／completion／acceptance 配置分别约束执行、完成和阶段验收，来源与摘要在合格 handoff 中绑定。

用户已确认的 [G4 实施方案](g4-message-gateway-plan.md) 与九张顺序任务卡已全部验收并发布。先两实体，再 6 点／8 线／6 矩形的 20 实体混合任务；固定一架一任务，观察链路恢复，两模式各 30 分钟及三个客户端。复用前重新核查正式包、同批消息、工具、端口及冻结输入，不将历史身份永久视为有效。GUI 默认 5555／9400／9500，无界面 5556／19400／19500，观察口 9999，两模式顺序运行。默认真实 1 倍、原 785 秒，自动预算 2700 秒，人工等待独立计时。

T06 的断线清理和整组重启已通过；在线重连／初始快照补齐及完整恢复矩阵已由 G4 验证，重置／场景切换分段归 G6。零高程缺省、Unicode 业务字段和第二机器部署限制保持。T05 的单次变速接受仅属于其历史运行；不设覆盖率门槛，算法／参数寻优归后续。

T09 正式发布 g4-t09-publish-20260920-115418-723744，package.json SHA256=dcc6b6294ff0687ae690f6518780b2ba563339b177ba7c79b22b3aa9ff41689e。原两实体两模式 passed，本轮真实 20 实体 GUI 确认已绑定原审查；审查后 1030 ms 推进导致原冻结检查 failed，保留原结果。相同候选完整受控复验 g4-t09-controlled-20260920-113903-072650 及关闭后独立审计 passed，正常退出／端口释放。正式日常入口 g4-t09-release-check-20260920-115528-388842 验证两种场景、中文空格工作目录、实际包导入、HTTP／WS 及网关停机自动恢复期间后端继续运行。见 [阶段报告](g4-stage-validation.md)及 [G5 交接](g4-g5-handoff.md)。
