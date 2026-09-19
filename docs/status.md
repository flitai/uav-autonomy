# 项目实施状态

更新日期：2026-09-19。依据：[总体实施计划](../04.项目总体实施计划与阶段验收.md)、[G0 报告](g0-baseline.md)、[Java 环境验收](g1-java-validation.md)、[T03 消息库验收](g1-lmcp-validation.md)、[T04 AMASE 验收](g1-amase-validation.md)、[T05 TCP 验收](g1-tcp-validation.md)、[G2 实施方案](g2-windows-uxas-plan.md)、[G3 实施方案](g3-system-integration-plan.md)、[任务清单](backlog.md)。过程记录见根级 [worklog.md](../worklog.md)。

## 当前关卡

**G0、G1、G2 已完成，G2-T01～T07 均已完成；G3-T01～T05 已完成，T06 可执行、尚未启动；G3 尚未完成。** 原生 UxAS 干净重建、连续三次启停、中文路径构建／运行、故障矩阵与正式发布通过，见 [T07 报告](g2-uxas-release-validation.md)。

| 项目 | 当前记录 |
| --- | --- |
| 最近通过的实现任务 | G3-T05：正式两模式完整任务、可靠 TaskComplete、覆盖统计正确性与正常退出；[报告](g3-completion-validation.md) |
| 源码基线 | T05 起点 `f357e96`，当时工作区干净；修改四个 AMASE Java 源文件并新增完成／统计验收。原 XML／UxAS／模型／生成代码保持；43 项 inputRevision=3 当前资格通过，旧修订和摘要保留 |
| 已归档历史 | G1-T01～T03 为 `304def9`，G1-T04 为 `f2f73ab`，G1-T05 为 `d77dd78`；T04 `b8ccf72`／`68ed420`、T05 `0fe8553`／交接 `5c2d387` 已推送 origin/main |
| 本轮变更 | [T05 报告](g3-completion-validation.md)：四个 AMASE Java 文件修复；11 组自动复验、本轮 GUI 确认／发布、UxAS 交接复验发布、inputRevision=3 资格及正式两模式全程通过。最终批次 `g3-t05-test-20260919-154803-742`；工作日志 WL-20260919-007／008；待完成提交和普通推送归档 |
| 当前正式批次 | AMASE `g1-t04-build-20260919-132521-005392`，Finalize `g1-t04-finalize-20260919-154103-934413`；UxAS 构建／验收 `g2-t05-build-20260919-101514-494`／`g2-t05-test-20260919-101831-478`，T07 发布 `g2-t07-publish-20260919-154459-188`；同批 LMCP 不变 |
| 已确定的 G2 路线 | MSVC v143＋CMake 3.31、Release x64／动态 CRT；固定 vcpkg baseline／overlay；Zyre／串口关闭，CZMQ／TCP 保留 |
| 已验证工具 | Temurin 11.0.32.1+1、Ant 1.10.18、Python 3.14.7 x64；Build Tools 17.14.41／cl 19.44.35229、SDK 工具 10.0.26100.7705、CMake 3.31.12、Ninja 1.13.2、固定 vcpkg 提交及工具 |
| 已验证能力 | G0～G2 与 T02～T04 能力保留；T05 完整任务目标及末段实际到达、唯一同源 TaskComplete、20 米栅格 seen／total／报告导出、独立逐格复算及相同事件两模式重放、正常退出 |
| 尚未完成验收 | T06 稳定性／故障矩阵及 T07 阶段复验／GUI 人工确认；在线自动重连／快照、重置分段、Cesium；Python 其他项目依赖 |
| 下一动作 | [G3-T06](backlog.md#6-g3-顺序与任务卡) 可执行、尚未启动：冻结本轮功能配置和产物，完成三次短程执行闭环、路径／故障、断线清理及整组重启复验 |
| 当前边界 | G3-T01～T05 已完成；正式两模式完整任务、可靠完成和统计正确性通过，不设最低覆盖率、不开展算法／参数寻优；G3 阶段仍待 T06／T07 |
| 本轮实际倍率 | 正式无界面全程 1 倍；GUI 实际 1→5→10 倍，用户明确接受本轮变速并要求保留记录。倍率审计及补充接受收据见 [T05 报告](g3-completion-validation.md)，不宣称正式 GUI 全程固定 1 倍 |
| 已确定的 G3 验收 | GUI／无界面分别完成任务执行，AMASE 20 米栅格覆盖计算与报告正确，本轮 GUI 确认及正常退出；不设最低覆盖率，算法／参数寻优归后续 |

## 已处理项与剩余缺口

| 项目 | 当前结论 | 下一次最小验证 | 归属 |
| --- | --- | --- | --- |
| Java／javac／Ant（R02 的 Java 部分） | 已构建 LmcpGen、统一消息库和 AMASE，固定版本在项目 .tools 下 | 后续复用受控环境，无需重新下载 | 后续复用 |
| 生成物管理（R07） | AMASE 构建、运行和配置副本均隔离；已成套发布，退出和端口释放通过 | 后续启动继续核对来源清单与端口 | 后续复用 |
| Java 源码与依赖兼容性 | AMASE 保持 source／target 11；统一消息库保留 Java 8 字节码，指定场景通过 | 新场景按任务验证；不宣称已在 JDK 8 运行 | 后续任务 |
| 生成器 CLI 诊断 | T02 检查诊断，T03 还检查输出文件、编译、类型清单与双向样本 | 后续保持输入／输出及版本校验 | 后续复用 |
| 消息库一致性及 Python（R03／R09） | 完整 AMASE 编译及指定场景的真实 TCP 状态使用新库通过；UXTASK 7→8 的兼容差异仍成立 | 其他场景的动态使用、双向命令按任务检查 | G3／后续场景 |
| GUI 重置与验收区间 | 人工重置触发既有全程时间单调检查，原 failed 记录保留；同版本受控复验与正常退出通过 | 重置及场景切换按不同时间段建立验收，不沿用全程单调假设 | G6 |
| AMASE 路径与地形（R06／R08） | 不同工作目录、中文空格路径通过；无 DTED 使用现有零高程缺省值 | 真实地形和高度验证仍需另备数据 | 后续地形验证 |
| AMASE 与 UxAS 封装（R04） | T02 正式真实双向 Sentinel／属性／LMCP、分包、来源和正常关闭通过 | G3 核查双向封装、来源过滤、完整执行／覆盖及基础断线处理；自动重连／快照补齐归 G4 | G3／G4 |
| C++／Node 与旧依赖补丁（R02／R10） | T01 工具链、T02 固定依赖及 T03 七模型 LMCP 通过，生成器／模型未变；微软目录描述哈希差异原因仍未知，实体已有独立签名验证；Node 留待 G5 | G2 构建、HelloWorld 和正式发布已通过；既有转换、符号性及弃用警告保留，其他服务按 G3 场景验证 | G2／G5 |

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
- 运行记录与临时探针分别位于 `out/runs/`、`out/tmp/`，不进入 Git。隔离故障副本不能充当正式工具。
- 各任务独立验收并追加根级工作日志；G1 已依据 T01～T05 的历史证据登记完成，不据此宣布原系统闭环通过。G2-T01～T07 已通过并登记 G2 完成；HelloWorld 内部消息不代表 AMASE↔UxAS 双向网络通过。
- G2 按 [阶段方案](g2-windows-uxas-plan.md)和七张任务卡推进。工具准备、依赖、LMCP 及 UxAS CMake 配置入口已验证；用 `configure-uxas.ps1` 和 `uxas-cmake.tests.ps1` 复核构建图，详见 [T04 报告](g2-uxas-cmake-validation.md)。完整构建与候选验收入口 `build-uxas.ps1`／`uxas-build.tests.ps1` 已通过，候选由构建／验收双编号解析；运行入口 run-uxas.ps1 和验收入口 uxas-helloworld.tests.ps1 已通过；最新候选双编号与正式包见 [T02 报告](g3-protocol-validation.md)，G2 历史身份见 [T07 报告](g2-uxas-release-validation.md)，T05／T06 报告保留历史批次。正式运行使用 run-uxas-release.ps1，脚本消费使用 Resolve-UxasPackage；复验和发布使用 uxas-release.tests.ps1／publish-uxas.ps1。

## 下一次工作的起点

当前 [G3-T05：任务完成与覆盖统计正确性](g3-completion-validation.md) 已完成。正式资格 `g3-t01-check-20260919-154623-382` 与两模式全程 `g3-t05-test-20260919-154803-742` 的 result／entry-result 均 passed。新 AMASE 本轮 GUI 确认、正常退出和发布完成；未改变 UxAS 二进制，按既有 T07 复验发布更新交接。当前 inputRevision=3、43 项冻结输入及原 90 点水道保持。两模式均为 724／724，独立逐格复算与相同记录两模式重放一致，19 项离线检查通过。T06 可执行、尚未启动；使用既有正式来源解析和本轮共同功能配置，不设最低覆盖率，不开展算法／参数寻优。具体批次和遗留边界见报告及工作日志 WL-20260919-007／008。

G1-T05 最终自动批次为 `g1-t05-automatic-20260917-222209-133086`，收尾批次为 `g1-t05-finalize-20260917-222451-856588`，均已通过；GUI 已正常退出。专题报告保留当时的历史快照。

G3 默认顺序验收两模式：GUI 使用 5555／9400／9500，无界面使用 5556／19400／19500，观察口均为 9999；必须核查所有端口归属。运行副本保留来源，取消静态状态及定时请求注入，初始真实数据齐全后触发任务。两模式默认 1 倍速，先运行原例 785 秒，仅为完成任务执行作必要调整，仿真上限 1800 秒、自动运行墙钟上限 2700 秒；不因低覆盖率调参或延长运行；详见阶段方案。G1-T05 不含发送或 UxAS 联调，G2 HelloWorld 不代表完整任务通过；自动重连／快照补齐归 G4，重置分段归 G6。
