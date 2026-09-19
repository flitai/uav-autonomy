# 项目实施状态

更新日期：2026-09-19。依据：[总体实施计划](../04.项目总体实施计划与阶段验收.md)、[G0 报告](g0-baseline.md)、[Java 环境验收](g1-java-validation.md)、[T03 消息库验收](g1-lmcp-validation.md)、[T04 AMASE 验收](g1-amase-validation.md)、[T05 TCP 验收](g1-tcp-validation.md)、[G2 实施方案](g2-windows-uxas-plan.md)、[G3 实施方案](g3-system-integration-plan.md)、[任务清单](backlog.md)。过程记录见根级 [worklog.md](../worklog.md)。

## 当前关卡

**G0、G1、G2 已完成，G2-T01～T07 均已完成；G3-T01 输入与验收基线已完成；G3-T02 已完成，G3 尚未完成。** 原生 UxAS 干净重建、连续三次启停、中文路径构建／运行、故障矩阵与正式发布通过，见 [T07 报告](g2-uxas-release-validation.md)。

| 项目 | 当前记录 |
| --- | --- |
| 最近通过的实现任务 | G3-T02：真实双向协议／来源、最小通信修复、正常退出与正式发布；[报告](g3-protocol-validation.md) |
| 源码基线 | T02 起点 `a1c814b`，工作区干净；已修复 Java TCP 接收分包及严格校验、UxAS 关闭和导出方向；原 XML／模型／生成代码不变 |
| 已归档历史 | G1-T01～T03 为 `304def9`，G1-T04 为 `f2f73ab`，G1-T05 为 `d77dd78`；T04 `b8ccf72`／`68ed420`、T05 `0fe8553`／交接 `5c2d387` 已推送 origin/main |
| 本轮变更 | [T02 报告](g3-protocol-validation.md)：本轮 GUI 确认、AMASE／UxAS 正式发布和六组正式协议复验通过；当前输入修订 2／43 项，验收不设覆盖率门槛；待 Git 归档 |
| 当前前置批次 | AMASE `g1-t04-build-20260919-101509-695450`，Finalize `g1-t04-finalize-20260919-103730-933619`；UxAS 构建／验收 `g2-t05-build-20260919-101514-494`／`g2-t05-test-20260919-101831-478`，T07 发布 `g2-t07-publish-20260919-104007-031`；同批 LMCP 不变 |
| 已确定的 G2 路线 | MSVC v143＋CMake 3.31、Release x64／动态 CRT；固定 vcpkg baseline／overlay；Zyre／串口关闭，CZMQ／TCP 保留 |
| 已验证工具 | Temurin 11.0.32.1+1、Ant 1.10.18、Python 3.14.7 x64；Build Tools 17.14.41／cl 19.44.35229、SDK 工具 10.0.26100.7705、CMake 3.31.12、Ninja 1.13.2、固定 vcpkg 提交及工具 |
| 已验证能力 | G0～G2 历史能力保留；T02 正式双向 TCP／直接连接、严格验收、分包／粘包、来源改写／PUB 过滤、命令去重、正常退出及整组重启 |
| 尚未验证能力 | 受控初始化、自主规划实际执行、完整任务与覆盖统计正确性、在线自动重连／快照、重置分段、Cesium；Python 其他项目依赖 |
| 下一动作 | [G3-T03](backlog.md#6-g3-顺序与任务卡)：暂停启动、连接就绪、两实体真实初始数据屏障与单次任务触发；可执行、尚未启动 |
| 当前边界 | G3-T01、T02 已完成；测试命令由 SendMessagesService 加载发送，未验证自主规划实际执行／完整搜索。覆盖统计正确性仍归 T05 |
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

T01 另确认：原任务 AllAny 在现有覆盖分析分支中直接返回，归 T05 语义核实、统计正确性对照及必要最小修复，不以调参绕过错误；重复 ViewAngleList／旧相机字段归 T02／T05，CMASI 请求无关联 ID、分段命令关联归 T04。详见 [八项 G3 风险](g3-input-baseline-validation.md#6-已确认风险与后续责任)，本轮没有覆盖率实测值。

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
- 运行记录与临时探针分别位于 `out/runs/`、`out/tmp/`，不进入 Git。隔离故障副本不能充当正式工具。
- 各任务独立验收并追加根级工作日志；G1 已依据 T01～T05 的历史证据登记完成，不据此宣布原系统闭环通过。G2-T01～T07 已通过并登记 G2 完成；HelloWorld 内部消息不代表 AMASE↔UxAS 双向网络通过。
- G2 按 [阶段方案](g2-windows-uxas-plan.md)和七张任务卡推进。工具准备、依赖、LMCP 及 UxAS CMake 配置入口已验证；用 `configure-uxas.ps1` 和 `uxas-cmake.tests.ps1` 复核构建图，详见 [T04 报告](g2-uxas-cmake-validation.md)。完整构建与候选验收入口 `build-uxas.ps1`／`uxas-build.tests.ps1` 已通过，候选由构建／验收双编号解析；运行入口 run-uxas.ps1 和验收入口 uxas-helloworld.tests.ps1 已通过；最新候选双编号与正式包见 [T02 报告](g3-protocol-validation.md)，G2 历史身份见 [T07 报告](g2-uxas-release-validation.md)，T05／T06 报告保留历史批次。正式运行使用 run-uxas-release.ps1，脚本消费使用 Resolve-UxasPackage；复验和发布使用 uxas-release.tests.ps1／publish-uxas.ps1。

## 下一次工作的起点

下一项为 [G3-T03：受控启动与初始化](backlog.md#6-g3-顺序与任务卡)，可执行、尚未启动。T02 正式协议收据 `g3-t02-verify-20260919-104721-817`、当前 43 项输入资格 `g3-t01-check-20260919-104119-819` 均通过；正式产物、GUI 确认与退出见 [T02 报告](g3-protocol-validation.md)。继续工作先复查当前来源，保留原场景，在独立副本建立暂停、真实初始配置／状态和任务初始化屏障，不以定时静态注入补齐。

G1-T05 最终自动批次为 `g1-t05-automatic-20260917-222209-133086`，收尾批次为 `g1-t05-finalize-20260917-222451-856588`，均已通过；GUI 已正常退出。专题报告保留当时的历史快照。

G3 默认顺序验收两模式：GUI 使用 5555／9400／9500，无界面使用 5556／19400／19500，观察口均为 9999；必须核查所有端口归属。运行副本保留来源，取消静态状态及定时请求注入，初始真实数据齐全后触发任务。两模式默认 1 倍速，先运行原例 785 秒，仅为完成任务执行作必要调整，仿真上限 1800 秒、自动运行墙钟上限 2700 秒；不因低覆盖率调参或延长运行；详见阶段方案。G1-T05 不含发送或 UxAS 联调，G2 HelloWorld 不代表完整任务通过；自动重连／快照补齐归 G4，重置分段归 G6。
