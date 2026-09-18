# 项目实施状态

更新日期：2026-09-18。依据：[总体实施计划](../04.项目总体实施计划与阶段验收.md)、[G0 报告](g0-baseline.md)、[Java 环境验收](g1-java-validation.md)、[T03 消息库验收](g1-lmcp-validation.md)、[T04 AMASE 验收](g1-amase-validation.md)、[T05 TCP 验收](g1-tcp-validation.md)、[G2 实施方案](g2-windows-uxas-plan.md)、[任务清单](backlog.md)。过程记录见根级 [worklog.md](../worklog.md)。

## 当前关卡

**G0、G1 已完成，G1-T01～T05 均已完成；G2-T01～T03 已完成，T04 可执行、尚未启动。** 七模型的 183 个 C++ 库源文件已原生编译，164 类型及三语言双向样本、错误拒绝、VS／Ninja 消费和迁移发布通过。证据见 [T01 记录](g2-cpp-toolchain-validation.md)、[T02 记录](g2-dependencies-validation.md)、[T03 记录](g2-lmcp-cpp-validation.md)。

| 项目 | 当前记录 |
| --- | --- |
| 最近通过的任务 | G2-T03：七模型 C++ LMCP、164 类型、六组验收、三语言字节一致及迁移消费通过 |
| 源码基线 | T03 起点 `1af7a91`，初始工作区干净；上游源码、G1 实现及生成产物保持不变 |
| 已归档历史 | G1-T01～T03 实现为 `304def9`，G1-T04 为 `f2f73ab`，G1-T05 为 `d77dd78`，均已推送到 origin/main；操作收尾记录另随文档提交归档 |
| 本轮变更 | T03 实现及报告已随 `f2dd834` 推送至 origin/main，14:42:43 核对远程完整标识一致；本条实际归档结果另随收尾文档提交。最终批次为 `g2-t03-build-20260918-143841-186`／`g2-t03-test-20260918-143927-259`，过程见 WL-20260918-007；T02 已随 `a13f698`、`1af7a91` 推送 |
| 已确定的 G2 路线 | MSVC v143＋CMake 3.31、Release x64／动态 CRT；vcpkg manifest 与固定 baseline／overlay；Zyre／串口默认关闭，CZMQ 保留。工具链与固定业务依赖组合均已验证 |
| 已验证工具 | 项目内 Temurin JDK 11.0.32.1+1、Ant 1.10.18；实际 Python 3.14.7 x64 已通过生成消息包验证，Git 2.55.0.windows.3；Build Tools 17.14.41／cl 19.44.35229、SDK 工具 10.0.26100.7705、CMake 3.31.12、Ninja 1.13.2、固定 vcpkg checkout 及 2026-07-27 工具通过完整验收 |
| 已验证能力 | 七模型 C++ 静态库、Java／Python／C++ 双向文件样本；C/C++ 工具及固定依赖探针；既有 GUI／无界面 TCP 状态与正常退出 |
| 尚未验证能力 | UxAS 构建、HelloWorld、UxAS 双向网络、完整重连、重置分段验收、原系统闭环、Cesium；Python 其他项目依赖 |
| 下一动作 | G2-T04：在根级 CMake 接入 UxAS 源码／服务清单和可选桥构建选项；尚未启动 |
| 当前边界 | 完成至 T03；未重新生成消息或运行仿真，未进入 T04；G1 验收保持历史记录，G2 阶段未完成 |

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
| AMASE 与 UxAS 封装（R04） | AMASE→Python 的真实 Sentinel／属性及 LMCP 双层校验、分包解析已通过；不代表 UxAS 双向兼容 | G3 核查双向封装、属性、来源过滤与闭环；完整重连留给后续 | G3／G4 |
| C++／Node 与旧依赖补丁（R02／R10） | T01 工具链、T02 固定依赖及 T03 七模型 LMCP 通过，生成器／模型未变；微软目录描述哈希差异原因仍未知，实体已有独立签名验证；Node 留待 G5 | T04 接入构建图，T05 按实际 UxAS 编译处理 CZMQ 宏等兼容问题 | G2／G5 |

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
- 运行记录与临时探针分别位于 `out/runs/`、`out/tmp/`，不进入 Git。隔离故障副本不能充当正式工具。
- 各任务独立验收并追加根级工作日志；G1 已依据 T01～T05 的历史证据登记完成，不据此宣布原系统闭环通过。G2-T01～T03 通过不等于 UxAS 或 G2 阶段通过。
- G2 按 [阶段方案](g2-windows-uxas-plan.md)和七张任务卡推进。工具准备、vcpkg 清单、依赖及根级 CMake 的 LMCP 构建入口已验证；UxAS 构建／运行入口仍为拟建内容。

## 下一次工作的起点

下一项为 [G2-T04 建立 UxAS CMake 入口](backlog.md#g2-t04建立-uxas-cmake-入口)，可执行、尚未启动；先核对 T02 合格依赖、T03 合格库及 G1 来源，按 Makefile 显式接入必需源码、服务与可选桥分支。若修改已登记的 LMCP 构建输入，必须重新构建／验收该库，不能改写旧来源清单。T05～T07 继续等待前置任务。

G1-T05 最终自动批次为 `g1-t05-automatic-20260917-222209-133086`，收尾批次为 `g1-t05-finalize-20260917-222451-856588`，均已通过；GUI 已正常退出。专题报告保留当时的历史快照。

后续并行运行 AMASE 时，GUI 使用 5555／9400／9500，无界面可使用 5556 和实体端口偏移 10000，不能只修改主端口。T05 不包含发送指令或 UxAS 联调。G2 默认 HelloWorld 不需要 AMASE 或其端口；双向协议、来源过滤与 WaterwaySearch 真实命令执行归 G3。
