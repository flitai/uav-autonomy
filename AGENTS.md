# uav-autonomy：AI 开发协作说明

适用范围：本仓库及其子目录。最后核对日期：2026-09-19。

这是项目级工作约定。遵循当前会话中更高优先级的指令和用户明确要求；修改子目录前检查是否还有适用于该目录的说明。源码、构建配置和实际运行结果用于判断工程事实，规划文档不代表功能已实现。

## 1. 项目目标与当前状态

本项目基于 LmcpGen、OpenAMASE、OpenUxAS，建设无人系统任务级仿真与自主策略研发环境。

当前改造方向：

1. 补齐 Windows 原生构建、启动、运行和部署能力。
2. 保留 OpenAMASE 仿真内核和 OpenUxAS 自主任务服务。
3. 新增消息网关，以 CesiumJS 三维 GIS 逐步替换原有态势可视化与操作界面。
4. 后续为 TorchRL／BenchMARL 训练集成复用协议与仿真控制接口。

截至上述核对日期，G0、G1 已完成，G1-T01～T05 均已完成；G2-T01 已完成，原生工具链十组验收及 VS／Ninja 在两类路径下的 C/C++ 探针通过；T02 已完成固定依赖的源码重建、11 组验收与迁移发布；T03 已完成七模型 C++ 库、164 类型及三语言双向样本验收和发布，T04 已完成 UxAS 构建图与独立桥配置探针，T05 已完成两类路径的候选构建及平台／来源验收，T06 已完成 HelloWorld 内部双向消息、正常退出与真实配置拒绝，T07 已完成复验和正式发布，G2 已完成；G3-T01～T05 已完成，见 [G3-T03 记录](docs/g3-startup-validation.md)、 [G3-T01 记录](docs/g3-input-baseline-validation.md)、 [T07 记录](docs/g2-uxas-release-validation.md)、[T06 记录](docs/g2-uxas-helloworld-validation.md)、 [T05 记录](docs/g2-uxas-build-validation.md)、[T01 记录](docs/g2-cpp-toolchain-validation.md)、[T02 记录](docs/g2-dependencies-validation.md)、[T03 记录](docs/g2-lmcp-cpp-validation.md)和 [T04 记录](docs/g2-uxas-cmake-validation.md)。G2 历史方案及任务卡见 [G2 实施方案](docs/g2-windows-uxas-plan.md)和 [G2 任务清单](docs/backlog.md#4-g2-顺序与任务卡)；当前按 [G3 实施方案](docs/g3-system-integration-plan.md)和 [G3 七张任务卡](docs/backlog.md#6-g3-顺序与任务卡)推进。项目内 Temurin JDK 11.0.32.1+1、Ant 1.10.18 已构建生成器、统一消息库和正式 AMASE；七模型已生成 Java／C++／Python 代码，Python 3.14.7 x64 的跨语言样本通过。T05 的 GUI／无界面真实 TCP 接收、十四组自动验收、GUI 人工确认、同版本受控复验及正常退出均完成；两层封装、分包、中文路径及故障处理已验证。证据见 [Java 验收](docs/g1-java-validation.md)、[T03 消息库验收](docs/g1-lmcp-validation.md)、[T04 AMASE 验收](docs/g1-amase-validation.md)和 [T05 TCP 验收](docs/g1-tcp-validation.md)。AMASE↔UxAS 双向协议及正式发布复验已通过；T05 已验证正式两模式完整任务、可靠 TaskComplete 与覆盖统计正确性，本轮新 AMASE GUI 确认／发布、UxAS 交接更新及来源修订通过；稳定性完整矩阵与在线重连未验证，也未落地 Cesium、消息网关或训练集成；Python 其他项目依赖未验证。继续工作时先读 [当前状态](docs/status.md) 与 [任务清单](docs/backlog.md)，并重新检查实际环境，不把历史快照当成永久结论。

G3 终点为 GUI／无界面分别完成 WaterwaySearch 任务执行，实际执行链可靠、AMASE 20 米栅格覆盖计算与报告正确、本轮 GUI 人工确认及正常退出。用户已明确当前重点是调通程序和系统，不设最低覆盖率，不开展为达指标的算法／参数寻优；覆盖效果优化归后续。完整水道保留，允许必要的功能兼容和统计正确性修复。基础断线清理及整组重启归 G3，自动重连／快照补齐归 G4，重置分段归 G6。T01 独立输入资格入口已验证，T02 独立协议编排／探针及通信修复已完成正式自动验收、本轮 GUI 确认和复验发布，见 [T02 报告](docs/g3-protocol-validation.md)；T03 已通过两模式真实初始化、单次任务请求、非空规划响应和正常收尾，见 [启动报告](docs/g3-startup-validation.md)；T04 已通过两模式分段命令、内部导航与任务航段关联及正常退出，见 [执行报告](docs/g3-execution-validation.md)；T05 已完成正式两模式全程、可靠 TaskComplete、统计独立复算和正常退出，见 [T05 报告](docs/g3-completion-validation.md)；T06 可执行、尚未启动。先读 [T01 输入基线](docs/g3-input-baseline-validation.md)，按其消息关联与八项风险继续。

Windows 原生运行是目标；WSL／Linux 可作参考或过渡环境，其验证结果必须单独标注。总体计划已确定首期默认 Windows 11 x64、联网开发与指定场景的基础离线演示，并保留原场景编辑器；实体规模和具体地理资源按任务细化。G2 已选定 MSVC v143／CMake 3.31、Release x64／动态 CRT 和 vcpkg manifest；Zyre／串口默认关闭，TCP 所需 CZMQ 保留。T01 已验证 MSVC／SDK／CMake／Ninja／vcpkg，固定业务依赖组合已由 T02 验证；Python 网关仍为后续候选实现。

## 2. 目录与职责

| 路径 | 用途 | 开发时关注 |
| --- | --- | --- |
| `LmcpGen/` | Java 编写的 LMCP 消息代码生成器 | Ant 构建；`src/templates/` 为各语言模板 |
| `OpenUxAS/mdms/` | CMASI、UXNATIVE、UXTASK、ROUTE 等消息模型 | 消息字段、类型、单位和版本的依据 |
| `OpenAMASE/OpenAMASE/` | AMASE 实际工程根目录 | 注意双层目录；Ant 构建与资源路径以此为基准 |
| `OpenAMASE/OpenAMASE/src/Core/` | 应用框架、事件、地图、地形、通用工具 | 显示依赖与仿真依赖可能交叉 |
| `OpenAMASE/OpenAMASE/src/Amase/` | 实体模型、仿真时间、任务分析、TCP 与界面 | 保留仿真语义，逐步分离显示和控制 |
| `OpenAMASE/OpenAMASE/src/SetupTool/` | 场景编辑 | 首期可继续保留，完整替换另行实施 |
| `OpenAMASE/OpenAMASE/config/` | GUI、headless、回放与场景编辑配置 | 通过插件配置组织运行模式 |
| `OpenUxAS/src/cpp/` | C++ 自主任务服务 | `Communications`、`Services`、`Tasks`、`Plans`、`Utilities` |
| `OpenUxAS/src/ada/` | Ada／SPARK 实现及证明相关资料 | 独立工具链，不默认纳入首期 C++ 移植 |
| `OpenUxAS/infrastructure/` | Anod 配方、Python 工具、示例编排 | 当前主流程依赖 Bash／Linux 环境 |
| `OpenUxAS/examples/` | 配置、消息与示例场景 | HelloWorld 和 WaterwaySearch 是首批验证入口 |
| `OpenUxAS/tests/` | C++ 测试及 SPARK 证明检查 | 检查测试入口的平台与依赖要求 |
| `OpenUxAS/resources/` | 辅助服务与资源 | 含参与 C++ 构建的 AutomationDiagramDataService |

改造初期保留三个现有源码目录的位置。`scripts/windows/` 已有通过完整验收的 C++ 工具准备／环境入口和独立 C/C++ 探针，以及 Java 工具、LmcpGen、统一消息生成和 AMASE 构建／运行入口；`scripts/lmcp/`、`scripts/amase/` 是标准库编排实现，`tests/lmcp/`、`tests/amase/` 保存消息及仿真验收探针。工具与模型清单分别见 `config/windows-java-toolchain.json`、`config/windows-cpp-toolchain.json`、`config/lmcp-models.json`；便携工具位于被忽略的 `.tools/`，MSVC／SDK 使用微软系统默认目录。根级 CMake 和 `cmake/` 已提供 LMCP 构建／包接口，`scripts/lmcp_cpp/`、`tests/lmcp_cpp/` 保存编排与验收；UxAS 目标及预设已接入，`scripts/uxas/`、`tests/uxas_cmake/` 保存配置编排和独立探针。计划中的 `src/sim_bridge/`、`apps/gis_gateway/`、`apps/cesium_viewer/` 等，需要在对应任务中实际创建；引用前先确认存在。

## 3. 开始任务时

1. 明确本次要求是分析、文档、实现、修复还是验证，只完成授权范围内的工作。
2. 运行 `git status --short`，识别用户现有修改和未跟踪文件；保留与本次任务无关的内容。
3. 检查适用的目录说明，阅读目标组件 README、实际构建配置及相关源码；优先用 `rg` 定位。
4. 根据任务按需阅读项目文档，不必每次加载全部长文：
   - [当前状态](docs/status.md)、[任务清单](docs/backlog.md)：当前关卡、缺口、下一任务及验收条件；历史基线见 [G0 报告](docs/g0-baseline.md)。
   - [G3 实施方案](docs/g3-system-integration-plan.md)：当前七卡顺序、双向连接、启动屏障、完整执行／覆盖统计正确性、后续优化及 G4 边界；T01 实际资格通过见 [输入基线](docs/g3-input-baseline-validation.md)，不等于闭环通过。
   - [G2 实施方案](docs/g2-windows-uxas-plan.md)：Windows 原生工具链、vcpkg 依赖、C++ 消息库、可选桥及 HelloWorld 的当前任务边界；规划入口不视为已实现命令。
   - [工作日志](worklog.md)：先读最近记录及当前任务关联的问题、尝试和决定，避免重复排查；新记录按第 10 节要求追加。
   - [总体实施计划与阶段验收](04.项目总体实施计划与阶段验收.md)：按用户主导、AI 逐项实施的方式推进，G0～G8 为任务细化与验收依据；首期采用联网开发、基础离线演示。
   - [目录分析与 Windows／Cesium 改造计划](03.项目目录分析与Windows_Cesium改造计划.md)：目录、技术方案及改造风险的参考。
   - [团队实施技术建议书与资源清单](02.OpenAMASE_OpenUxAS_TorchRL_BenchMARL_团队实施技术建议书与资源清单.md)：仿真与训练的长期设计。
   - [思路与技术途径参考](01.无人自主智能策略研发_思路与技术途径参考.md)：研究背景与目标。
5. 检查所需工具是否真实可用。`PATH` 未找到命令只代表当前会话未找到；WindowsApps 的 Python 入口也不能代替解释器可用性检查。
6. 选择能验证本次修改的最小闭环。对已明确且可逆的任务继续执行；缺少会影响架构或验收的必要信息时，说明具体问题，同时推进不依赖答案的工作。

默认使用中文沟通和编写项目说明，代码标识符沿用现有语言和命名习惯。区分“源码确认”“实际执行通过”“推测／待验证”，不将计划或静态阅读写成运行结果。

## 4. 构建与运行入口

以下区分已验证的工具入口和后续工程构建参考。逐条执行并检查退出码；构建步骤失败后不要继续使用旧产物冒充成功。

### Windows：Java 工程

工作目录为仓库根目录，以下工具准备与验收入口已在 PowerShell 5.1 验证：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-java.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\java-toolchain.tests.ps1
# 在新的交互 PowerShell 进程启用工具，关闭该进程即可结束本次启用。
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File .\scripts\windows\use-java.ps1
```

脚本仅修改进程环境；不永久修改 PATH 或执行策略。版本、来源、校验和输出策略见 [Java 环境验收](docs/g1-java-validation.md)。后续构建脚本应在自己的进程内调用 use-java.ps1，不能依赖已经退出的子进程留下环境变量。

LmcpGen 的以下入口已通过实际构建与六组验收；构建脚本自行启用锁定工具并恢复进程环境，不要求父终端提前启用 Java：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-lmcpgen.ps1
# 先完成一次构建，再运行含隔离故障场景的复验。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\lmcpgen-build.tests.ps1
```

构建使用独立的 `out/build/lmcpgen/<run-id>/`，验证通过后发布 `out/artifacts/lmcpgen/LmcpGen.jar` 与 `build-info.json`；原始记录在 `out/runs/<run-id>/`。失败时检查本次 result.json，不把保留的旧产物当成本次成功。来源清单包括实际输入哈希、工具版本、Git 基线及 CLI 结果。`-checkMDM` 可能在出错时仍退出 0，必须检查输入存在和诊断输出；T02 的检查范围仅为 CMASI 读取入口，七模型统一生成及跨语言验证已由下述 T03 入口完成。

AMASE 的构建和自动验收入口已实际运行。构建只产生候选批次；正式发布要求自动验收、GUI 人工确认及正常退出全部完成：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-amase.ps1 -PythonExecutable $pythonExe
# 以实际构建编号替换占位符。GUI 自动运行至少 20 秒后暂停并保留。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-amase.ps1 -Mode Gui -BuildRunId '<BUILD_RUN_ID>' -ValidateRun -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\amase.tests.ps1 -BuildRunId '<BUILD_RUN_ID>' -GuiRunId '<GUI_RUN_ID>' -PythonExecutable $pythonExe
```

构建入口保留 AMASE 的 source／target 11，通过 `file.reference.lmcplib.jar` 指向新库并显式列出依赖，禁止 lib 通配符混入旧库。候选位于 `out/build/amase/<run-id>/candidate/`；验收入口 Finalize 仅在取得真实人工确认后正常关闭 GUI 并发布 `out/artifacts/amase/`。发布后启动可省略 BuildRunId。具体参数和证据见 [T04 报告](docs/g1-amase-validation.md)。

GUI 默认端口为 5555，实体 400／500 另监听 9400／9500。并行无界面验收使用 `-Mode Headless -Port 5556 -EntityPortOffset 10000`，实体端口为 19400／19500；必须显式配置和核查所有端口，不静默换端口，不结束其他进程。每次运行复制配置、原场景和资源到独立 out/runs 目录；无 DTED 的零高程缺省值不代表真实地形已验证。内部事件验收插件不实现 T05 的 TCP 接收。

实际 TCP 接收与验收由独立的 scripts/validation 和 tests/amase_tcp 实现，不改动上述已验收构建输入。以下入口已通过两种模式的真实接收和十四组自动检查，使用已验证的 Python 3.14.7 x64：

```powershell
# 连接本次仍在运行的正式 AMASE；不能填写已经退出的历史运行编号。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\receive-amase.ps1 -AmaseRunId '<AMASE_RUN_ID>' -PythonExecutable $pythonExe
# 自动编排两种模式并保留 GUI 供本轮人工确认；关闭与收尾按 T05 报告执行 Finalize。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\amase-tcp.tests.ps1 -PythonExecutable $pythonExe
```

客户端只接收，不发送控制或订阅消息；绑定本次 PID／监听端口、正式产物和类加载来源。验证 Sentinel 和内部 LMCP 的长度与实际校验和，再调用统一 Python 类解码；不能把 getObject 或零校验和宽松接受当成完整验证。原始字节、完整帧范围、统计及未消费尾部保存在独立 out/runs；int64 标识和时间写成字符串，仿真毫秒不转换成 UTC。实际 AMASE→Python 接收不代表 UxAS 双向或完整重连矩阵通过。

现有 ValidateRun 对整个 GUI 运行采用时间单调检查；人工重置会触发失败，即使应用正常退出。保留这类诊断并以同版本受控复验完成收尾，不修改原记录或来源清单绕过检查；重置和场景切换的分段验收归 G6。

统一消息生成与验收入口已验证，工作目录同样为仓库根目录。Python 参数必须指向已核查的 Python 3.14.7 x64；以下变量赋值适用于本轮已核查的安装布局，可按实际安装位置替换：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\generate-lmcp.ps1 -PythonExecutable $pythonExe
# 先完成一次生成，再运行含隔离故障场景的复验。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\lmcp-generation.tests.ps1 -PythonExecutable $pythonExe
```

三种语言的代码已位于 `out/generated/lmcp/{java,cpp,py}/`，Java 库为 `out/artifacts/lmcp/java/lmcplib.jar`。使用前核对生成目录 generation-info.json 与产物目录 build-info.json 的运行编号和哈希，禁止混用不同批次或故障副本；失败不会发布部分结果。Python 验证仅导入消息包，示例 LMCPClient.py 在导入时会连接网络，不能当普通模块批量导入。C++ 已在 G2-T03 编译并验证三语言样本，消费入口见下节；AMASE 已实际构建并验证新库的类加载来源，全部任务状态以 status 为准。

### Windows：C++ 工具准备

固定清单见 `config/windows-cpp-toolchain.json`，来源修复、实际版本与完整验收见 [T01 记录](docs/g2-cpp-toolchain-validation.md)。以下入口已在 PowerShell 5.1 验证：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-cpp.ps1
# 只检查已有工具，不下载或安装。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-cpp.ps1 -VerifyOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\cpp-toolchain.tests.ps1
# 新交互进程启用工具，关闭进程即结束本次启用。
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File .\scripts\windows\use-cpp.ps1
```

Build Tools 17.14.41／v143、SDK 发布 10.0.26100.7705、CMake 3.31.12、Ninja 1.13.2 和固定 vcpkg 已通过来源与真实编译验收。工具目录、编译器文件及实际加载 CRT 的版本分别记录；不要通过猜测目录名判断版本。来源校验不符时停止，不用新的下载哈希自行替换信任值；T01 的目录摘要更正有独立的微软原生签名验证和篡改拒绝证据。

准备／验收入口恢复自己的进程环境，`use-cpp.ps1` 在当前进程启用 Host／Target x64；后续脚本自行启用并恢复，不依赖已退出的子进程。vcpkg 强制使用已验证的 CMake／Ninja，未执行全局集成或持久 PATH 修改。十组验收覆盖 VS／Ninja、Release x64／动态 CRT、普通／中文空格路径、不同工作目录和隔离故障；此为 T01 工具链证据；T02 业务依赖及 T03 LMCP 另经下述入口验收，UxAS 仍待后续。

### Windows：固定第三方依赖

T02 已验证 89 个 ports（含 81 个 Boost 历史模块／辅助 ports），业务版本、来源及兼容限制见 [T02 记录](docs/g2-dependencies-validation.md)。根级 `vcpkg.json`、`vcpkg-configuration.json`、`config/windows-dependencies.json` 和 `config/vcpkg/` 为实际清单／配方。主机辅助工具留在 `.tools/`，不永久修改 PATH。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-deps.ps1 -Rebuild
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\deps.tests.ps1 -BuildRunId '<BUILD_RUN_ID>'
```

构建只生成候选；验收包含 VS／Ninja、真实帧／数据库／XML／Boost 功能、CRT、中文空格路径、故障和迁移。成功后原子更新 `out/artifacts/deps/current.json`，保留旧批次和指针备份。后续脚本点入 `deps-common.ps1`，用 `Resolve-DepsPackage` 核对构建／验收身份及全部输入／安装哈希，再消费 `UxasDependencies`／`UxasDeps::*`；CMake 配置不隐式安装依赖。无 `-Rebuild` 时可复用匹配 ABI 的二进制缓存，不能将缓存恢复计作本次源码编译。

依赖包只验收 Release x64／动态 CRT。CZMQ 旧 `snprintf` 宏和 CMake 3.31／Ninja 的中文响应文件处理见 T02 报告，固定依赖已通过 T05 的 UxAS 完整编译与候选验收。G2-T01～T07 已完成，G2 验收通过；G3-T01～T05 已完成，T06 可执行、尚未启动，详见 [T05 报告](docs/g3-completion-validation.md)。

### Windows：统一 C++ LMCP 库

T03 从 G1 同批生成代码编译全部七模型，根级 CMake 默认提供 LMCP 库与文件探针；UxAS 预设另行启用可执行目标。入口自行核对工具、T02 合格依赖、G1 生成输入及全部生成文件，禁止手改生成输出或来源清单。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-lmcp-cpp.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\lmcp-cpp.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>'
. .\scripts\windows\lmcp-cpp-common.ps1
$lmcpPrefix = Resolve-LmcpCppPackage -PythonExecutable $pythonExe
```

构建创建独立候选，验收通过后发布 `out/artifacts/lmcp/cpp/<build-run-id>/<validation-run-id>/` 并原子更新 current.json，保留旧批次。CMake 包 `UxasLmcp` 提供 `Uxas::lmcp`；后续先解析合格包再配置，不隐式安装依赖。根 CMake 或已登记输入变化时重新构建／验收，不改写旧清单。独立 C++ 来源记录关联 G1 父级，不能覆盖 Java 或 AMASE 的历史清单。

183 个源文件、382 个头文件、164 类型及六个双向样本已验证，详情见 [T03 报告](docs/g2-lmcp-cpp-validation.md)。帧长与校验防线属于文件探针；生成工厂允许零校验和，并未在此完成网络输入防护。T03 不代表 UxAS 构建或双向协议通过，主工程仍验收 Release x64／v143／C++14／MD。

### Windows：UxAS CMake 配置与独立桥探针

T04 已验证 122 个必需编译单元、40 项服务注册、5 个嵌入资源及 qualified LMCP／依赖链接图。以下入口接受明确的 Python 3.14.7 x64 路径，自行启用并恢复工具环境：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\configure-uxas.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-cmake.tests.ps1 -PythonExecutable $pythonExe -ConfigureRunId '<CONFIGURE_RUN_ID>'
```

结果与 File API 证据位于 `out/build/uxas/`、`out/runs/`。配置入口只登记 configured，不构建 uxas.exe；验收只构建两个独立桥能力探针，完整编译与 HelloWorld 分别归 T05／T06。直接使用 `windows-uxas-release` 预设仍需合格来源上下文。默认关闭 Zyre／串口，当前请求 ON 会明确失败；CZMQ、TCP 与其余必需服务保留。修改根 CMake／cmake 输入后必须按 T03 入口重新构建并验收消息库。详见 [T04 报告](docs/g2-uxas-cmake-validation.md)。

### Windows：UxAS 候选构建与验收

T05 已验证两类路径的干净 Release x64 构建、平台与来源检查。入口使用已验证的 Python 3.14.7 x64，环境仅在本次进程内启用并恢复：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-uxas.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-build.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>'
```

候选位于 `out/build/uxas/<build-run-id>/candidate/`；独立验收收据位于 `out/runs/<validation-run-id>/acceptance.json`。T06 必须使用 `Resolve-UxasCandidate` 同时绑定两个编号并复查来源，解析接口见 [T05 报告](docs/g2-uxas-build-validation.md)，最新有效编号见 [T07 报告](docs/g2-uxas-release-validation.md)。失败不发布或覆盖旧包；候选入口不切换正式指针，正式发布由 T07 入口完成，未捆绑 CRT。程序通过清单启用进程 UTF-8，Boost.Filesystem 使用独立 UTF-8／UTF-16 facet，不修改全局 locale。

T05 的未知参数冒烟在服务启动前返回原有 `-1`，不代表 HelloWorld 运行通过；不要用现有 `-version` 当作会立即退出的探针。真实 HelloWorld 服务启停、消息证据与主程序关闭桥拒绝已由 T06 验证；T07 完整矩阵与正式发布也已通过，见 [T07 报告](docs/g2-uxas-release-validation.md)。

### Windows：HelloWorld 运行与验收

T06 已通过原配置 10 秒、1000／5001 ms 周期的真实内部总线双向接收和正常退出；普通／中文空格运行目录、缺失配置与关闭桥拒绝均通过。入口先用双编号解析候选，保留原 XML，30 秒进程超时；超时和强制终止只算失败。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-uxas.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>' -ValidationRunId '<VALIDATION_RUN_ID>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-helloworld.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>' -ValidationRunId '<VALIDATION_RUN_ID>'
```

运行入口仅支持默认 `-Example HelloWorld`，不启动 AMASE 或外部 TCP 桥。记录位于独立 out/runs，同时检查 result 与 entry-result 成功及来源哈希；自动验收另有 acceptance.json。运行编排和反例位于 scripts/uxas_runtime、tests/uxas_runtime，单独登记输入，未改变旧构建来源规则。

为取得配置、服务 ID 和退出证据，UxAS 目标启用原有 UXAS_INFO_LOGGING_ENABLED；因此 T03／T04／T05 已重新完整验收。T06 历史批次见 [T06 报告](docs/g2-uxas-helloworld-validation.md)，最新候选和正式批次见 [T07 报告](docs/g2-uxas-release-validation.md)。G2 已完成；外部协议已由 G3-T02 验证，受控初始化由 T03 验证，完整执行与统计正确性已由 T05 验证。

### Windows：正式 UxAS 与 G2 复验发布

T07 已完成干净重建、连续三次正常启停、中文路径构建／运行、真实 UxAS 超时和隔离故障矩阵。正式 HelloWorld 入口自动解析 out/artifacts/uxas/current.json，复查候选、T06／T07 收据、发布记录、包文件及当前 CRT：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-uxas-release.ps1 -PythonExecutable $pythonExe
```

重新发布先完成 build-uxas.ps1、uxas-build.tests.ps1、uxas-helloworld.tests.ps1，再调用 uxas-release.tests.ps1（PythonExecutable、BuildRunId、ValidationRunId、HelloWorldRunId 必填）和 publish-uxas.ps1（PythonExecutable、ReleaseRunId 必填）。完整命令、批次和边界见 [T07 报告](docs/g2-uxas-release-validation.md)。脚本消费使用 uxas-release-common.ps1 的 Resolve-UxasPackage，返回经复查的正式包目录。

scripts/uxas_release、tests/uxas_release 独立登记来源；包按构建／T07 验收／发布编号保留，原子切换指针，失败保留或恢复旧包／指针。正式包不捆绑 CRT，开发工作区来源记录仍是消费前提；第二机器部署和离线演示归 G8。G2 已完成，G3-T01 已完成，不把输入资格、内部消息或编入 TCP 服务视为 AMASE 双向通过。

### Windows：G3 输入资格基线

T01 已验证下列独立入口，复用正式包资格接口并核查 AMASE、工具、CRT、同批七模型和原例输入；不启动仿真或 TCP 联调：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\check-g3-baseline.ps1 -PythonExecutable $pythonExe
```

来源与当前契约为 config/g3-baseline.json（acceptanceRevision=2，不设最低覆盖率；inputRevision=3，43 个当前来源，T02／T05 修复与旧哈希另行登记），结果在独立 out/runs；T01 原报告／收据保留历史口径，不改写为新口径验收；只有 result 与 entry-result 均 passed 才算通过。输入变化按影响重建／复验，不改写旧清单。真实双向协议与来源过滤归 T02，运行编排／插件归 T03，命令实际执行归 T04，完整完成／覆盖归 T05；现有 AllAny 覆盖分支与旧 XML 字段风险见 [T01 报告](docs/g3-input-baseline-validation.md)。

### Windows：G3 双向协议验收

T02 已通过真实 AMASE／UxAS 直连、分包／粘包、来源／PUB 过滤、命令去重、断线残包后的整组重启和正常关闭；独立于 G1／G2，不等于自主规划或完整任务已通过。使用当前正式产物及输入资格编号：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-protocol.tests.ps1 -PythonExecutable $pythonExe -BaselineRunId g3-t01-check-20260919-104119-819
```

来源改变时先重跑 check-g3-baseline.ps1，使用新的合格编号。主桥显式 ConsiderSelfGenerated=false、ExportOnlyLocalMessages=true；观察口完整订阅且不回送消息，不能依赖 PUB 提供全部状态。正式产物、候选诊断参数与边界见 [T02 报告](docs/g3-protocol-validation.md)。T02 测试屏障只保证协议取样；T03 已另行验证初始数据和任务请求屏障；T04 局部规划执行已通过；T05 正式全程完成／覆盖统计对照及新发布复验已通过，在线重连／快照归 G4。

### Windows：G3 受控启动与初始化

T03 独立编排、AMASE 插件与默认配置已通过两模式真实初始化、11 组运行／故障、10 项屏障反例及独立 GUI 正常收尾。入口仅支持 startup 验收范围，取得非空规划响应后收尾，不代表实际任务执行或覆盖统计通过：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3.ps1 -PythonExecutable $pythonExe -Mode Headless
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-startup.tests.ps1 -PythonExecutable $pythonExe
# 可选 GUI 观察：运行入口加 -Mode Gui -KeepGui；用本次运行编号收尾。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\finish-g3-gui.ps1 -PythonExecutable $pythonExe -RunId '<G3_RUN_ID>'
```

运行／验收接受 Configuration、RunId 和可选 BaselineRunId，默认重新做只读来源资格复查；详情见 [T03 报告](docs/g3-startup-validation.md)。当前正式二进制与 43 项冻结输入不变，新插件在 out/build 单独编译。原 XML 保留，运行副本移除 SendMessagesService；两实体真实初始数据齐全、TaskInitialized 到达后才发单次请求。

主桥保留 AMASE 来源；控制观察桥显式 ConsiderSelfGenerated=true，将少量编排注入登记为本地桥来源，观察客户端不回送所收消息。自身注入被该桥过滤，来源改写须看 UxAS 原消息日志，不能据缺少回显判失败。初始化整体、任务初始化、规划和关闭各 30 秒，整次上限 2700 秒。GUI 收尾只表示正常关闭，不代替 T07 人工确认。

中文运行目录已通过；原消息库通用 Unicode 字符串仍有长度／编码边界。编排标识使用 ASCII，场景从运行目录相对加载；涉及中文业务字段时按模板／生成器统一修复并重新验收，不手改生成文件。T04 已另行验证规划命令实际执行，T05 正式全任务与覆盖统计对照已通过，见 [完成报告](docs/g3-completion-validation.md)。

### Windows：G3 规划命令实际执行

T04 已完成两模式真实规划、分段命令、内部导航及任务航段推进，23 项离线反例／边界检查通过。入口复用 T03，新增只读 EntityModule 记录网络采样间的目标航点变化；正式包、原配置和算法保持，详见 [T04 报告](docs/g3-execution-validation.md)。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3-execution.ps1 -PythonExecutable $pythonExe -Mode Headless
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-execution.tests.ps1 -PythonExecutable $pythonExe
```

默认 config/g3-execution.json，独立 g3-t04- 运行编号；接受 Configuration 和可选 BaselineRunId。验证两真实执行分段、四个任务目标及至少两段实际推进后正常关闭，不等待完整任务。原示例实际 TurnShort、四点重叠均保留；不能把网络状态跳号直接当成遗漏执行，须核对内部导航。完整完成及覆盖统计已由 T05 另行验收，不设覆盖率门槛；T07 仍需全程 GUI 人工确认。

### Windows：G3 任务完成与覆盖统计

T05 已完成正式 GUI／无界面全程执行、可靠 TaskComplete、724 格逐格独立复算和 19 项完成／统计检查，正常退出与端口释放通过。入口为 run-g3-completion.ps1／g3-completion.tests.ps1，配置为 config/g3-completion.json，详见 [T05 报告](docs/g3-completion-validation.md)。原 90 点水道、20 米、785 秒、默认启动 1 倍及业务参数保持；两次实测均为 724／724，不设覆盖率门槛、不开展算法／参数寻优。本轮正式 GUI 实际 1→5→10 倍，用户已明确接受该单次差异，原始倍率和补充收据保持；后续仍须核对实际 SessionStatus，不能仅凭启动配置宣称全程 1 倍。

本轮四项 AMASE 源码修复已重建，通过 11 组自动复验、用户真实 GUI 确认、正常退出和发布；未变更 UxAS 二进制按既有 T07 流程复验发布以更新 AMASE handoff。inputRevision=3 保留旧修订和摘要，当前资格与正式两模式收据见 T05 报告。T06 可执行、尚未启动，T07 仍需阶段全程 GUI 人工确认。

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g3-completion.ps1 -PythonExecutable $pythonExe -Mode Headless
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-completion.tests.ps1 -PythonExecutable $pythonExe
```

### Linux／WSL：现有 UxAS 参考流程

以下使用 Bash，工作目录为 `OpenUxAS/`，不是 Windows 原生命令：

```bash
./anod build uxas
./anod build amase
./run-example 01_HelloWorld
./run-example 02_Example_WaterwaySearch
```

Anod 可能下载依赖或使用独立检出的 AMASE／LmcpGen；运行前检查 `infrastructure/specs/config/repositories.yaml` 和实际源码解析结果，确保测试的是预期版本。

C++ 测试入口为 `OpenUxAS/tests/cpp/run-tests`，在其所在目录执行 `./run-tests`；该入口也是 Bash，依赖已构建环境。详细说明见 [C++ 测试 README](OpenUxAS/tests/cpp/README.md)。

当前没有已验证的根级 `cmake --preset`、`npm run dev` 或 `pytest` 流程。只有创建并验证相应配置后，才把它们记为本项目标准命令。旧 `.bat` 脚本和无界面配置也需核对路径、输出位置和行为，不能仅因文件存在就视为可运行。

## 5. 架构边界

- **OpenAMASE**：仿真状态、运动与命令执行、仿真时间、相关分析结果的来源。
- **OpenUxAS**：自主任务、分配、规划与消息服务。
- **LMCP／MDM**：跨语言后端消息契约。
- **消息网关（拟建）**：协议适配、快照与增量、时间映射、记录和浏览器接口。
- **CesiumJS（拟建）**：三维显示和用户交互。浏览器掉帧、相机操作或底图变化不能改变仿真结果。
- **训练适配（后续）**：复用协议和进程控制核心，不另建一套不一致的消息解析与时间语义。

优先从“Windows 构建与协议验证 → 原有示例闭环 → 网关 → Cesium 显示 → 控制／回放 → 打包验收”推进。模拟消息可用于独立前端开发，但不能作为端到端联调通过的证据。

## 6. 必须保留的技术约束

### 消息与连接

- Java／C++／Python 消息库来自同一份 MDM 和生成器基线。修改消息或生成行为时，改 MDM／模板／生成器并重新生成，不仅修补生成文件。
- T03 已确认当前 Java 模板与 AMASE 随库 Java 库的 `packMessage(..., true)` 输出 Sentinel／属性封装，`getMessageBytes` 解析该外层；AMASE 发送继续调用 packMessage；T02 将接收替换为严格 SentinelMessageReader，修复分包丢帧并校验两层长度与校验和。Python 工厂输出原始 LMCP，不能把两者直接等同。真实双向兼容、分包、过滤与来源已完成正式验收，见 [T02 报告](docs/g3-protocol-validation.md)；不得沿用 G0 的“AMASE TCP 仅原始 LMCP”判断。
- 统一消息库的 UXTASK 为版本 8，旧随库库为版本 7；RendezvousTask 部分旧接口被当前模型移除，不能宣称完全向后兼容。AMASE 完整构建及 WaterwaySearch 已使用新库运行；其他场景、动态调用和实际网络仍按后续任务验证。
- WaterwaySearch 的 `5555` 为 AMASE TCP；UxAS `5560` 为 PUB、`5561` 为 PULL，`9999` 为另一 TCP 出口。这是示例端口，不应硬编码为所有实例的全局常量。
- UxAS PUB 桥对来源 EntityID 有过滤；不能假定订阅后自然取得所有 AMASE 状态。
- TCP 需要增量分包、长度与校验检查、断线清理；不要把一次 `recv` 当成一条完整 LMCP 消息。
- 明确消息来源与转发方向，避免重复指令和回路。命令发送成功、后端接受和实际执行完成是不同状态。
- 浏览器接口应版本化，提供初始快照和有序增量。对外的 int64 实体／任务／命令 ID 使用字符串，避免 JavaScript 精度损失。

协议相关修改优先查看 [AMASE TcpServer](OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/TcpServer.java)、[UxAS TCP 桥](OpenUxAS/src/cpp/Communications/LmcpObjectNetworkTcpBridge.cpp)、[UxAS 属性消息收发](OpenUxAS/src/cpp/Communications/ZeroMq/ZmqAttributedMsgSenderReceiver.cpp) 和 [WaterwaySearch 配置](OpenUxAS/examples/02_Example_WaterwaySearch/cfg_WaterwaySearch.xml)。

### 时间、坐标与地形

- 保留源时间、单位与基准；仿真时间和墙钟时间分别处理。AMASE 实体时间不能未经确认直接解释为 UTC。
- 浏览器时钟跟随后端；暂停、重置、场景切换和回放切换时清理旧样本并重新同步。
- 无界面模式不等于已有远程控制或严格同步单步接口。`SessionStatus` 是状态消息，不能假定设置它就能完成开始／暂停／倍速操作。
- CMASI 经纬度单位为度、高度为米；明确经纬度顺序，按字段单位做转换。
- `AltitudeType.MSL` 的本地注释存在基准歧义。追踪实际计算和数据来源后再转换高度，不能统一盲加高程修正。
- 姿态需要校核真北航向、机体系、Cesium 参考系和模型轴，不能直接复用一组欧拉角。
- AMASE 地形可能参与仿真与视线计算；替换显示不等于替换地形计算。WorldWind 还被 Shapefile 代码使用，确认依赖后再移除。

字段定义以 [CMASI.xml](OpenUxAS/mdms/CMASI.xml) 为依据；时间行为检查 [SimTimer.java](OpenAMASE/OpenAMASE/src/Amase/avtas/amase/util/SimTimer.java) 与 [EntityModel.java](OpenAMASE/OpenAMASE/src/Amase/avtas/amase/entity/EntityModel.java)。

## 7. 修改规范

- 小范围修改，沿用目标模块的格式、命名和错误处理习惯；避免在移植时同时重构算法、升级全部依赖或移动上游目录。
- 保留原有版权说明、许可证和来源信息。新依赖记录用途及固定版本；新增前先检查已有组件是否足够。
- C++ 当前主构建使用 C++11；Java 源码级别见项目配置。升级标准或工具链需有具体兼容理由与验证记录。
- 新增 Windows 脚本用脚本自身位置解析路径，显式设置工作目录；正确处理空格、中文路径和退出码。
- 管理本次启动的进程、端口和运行目录；就绪检测区分进程存活、连接成功、消息可解析和初始状态齐全。
- Windows 文件操作使用原生 PowerShell 和明确路径。递归清理前确认目标位于预期输出目录，不以宽泛进程名结束其他 Java／Python／UxAS 实例。
- 默认以 UTF-8 读写文本；不顺手格式化全库或统一全部行尾。Windows 批处理与 Shell 脚本按各自运行要求处理。
- 不提交生成物、依赖缓存、程序原始运行日志或本机绝对路径；检查实际 `.gitignore`，不假定规则已存在。保留上游有意携带的 JAR 和资源。根级 `worklog.md` 是人工维护的项目文档，应保留在版本管理范围内；是否提交仍遵循用户授权。
- 不覆盖无关用户修改。用户已于 2026-09-18 持续授权：确认阶段性工作完成且相关验收通过后，自动提交并推送本次任务改动，无需逐次确认；用户后续明确要求暂不提交或推送时，以该次要求为准。提交前检查范围、敏感信息及忽略规则，不夹带无关修改；使用普通推送，不强推或改写已发布历史。推送受阻时保留本地提交，记录原因和恢复条件，不将失败写成已归档。

## 8. 验证与完成标准

按修改风险选择必要验证，不为纯文档或简单可逆修改增加无关测试。

| 修改类型 | 至少核查 |
| --- | --- |
| 文档／AI 说明 | 路径与链接存在，命令工作目录正确，现状与计划分开，Markdown 和 UTF-8 正常 |
| MDM／生成器 | 重新生成；相关语言可构建；跨语言往返结果和固定样本一致 |
| C++ 构建／平台适配 | 目标平台构建；HelloWorld；涉及通信或规划时运行相关集成示例 |
| 消息桥／网关 | 双向协议、半包／粘包、来源过滤、重连、初始快照、重复消息与退出行为 |
| 仿真控制 | 开始／暂停／倍速／重置的真实后端行为、时间连续性和旧运行隔离 |
| Cesium 显示 | 真实消息驱动、已知坐标与姿态、后端时间、对象删除、刷新／重连、产物资源加载 |
| 启动／部署 | 不同工作目录和含空格路径、依赖缺失／端口冲突、反复启停、日志与退出状态 |

无法执行时准确说明原因、已完成的静态检查及尚缺的验证；不将编译成功等同于联调成功，不将仿真窗口打开等同于任务链路正确。性能数值只有在说明机器、场景、实体数、更新率和测量方式后才作为实测结果报告。

每次阶段性任务收尾，先按第 10 节追加根级 `worklog.md` 并同步相关状态；确认完成且验收通过后，按第 7 节持续授权提交、推送并核对远程结果，再给出交付回复。工作日志是任务交付的一部分。回复简要说明：改了什么、主要文件、实际验证结果、提交／推送状态及剩余限制。重大接口或构建入口改变时同步更新相关说明，避免后续 AI 使用过期信息。

## 9. 本说明的维护

`AGENTS.md` 是完整规范的唯一维护入口，`CLAUDE.md` 引用本文件。只记录稳定的项目约定与可核查事实；临时故障、单次任务日志、长篇调研放入对应文档，不持续堆积在本文件中。

完成 Windows 构建、网关或 Cesium 集成后，更新当前状态、标准命令及验证入口。规划中的目录或能力只有在实际落地后才能改写为“已有”。

## 10. 固定工作流程与工作日志

根目录 [worklog.md](worklog.md) 是固定、持续追加的工作日志。此约定来自用户明确要求，适用于后续分析、规划、实现、修复、验证和文档类阶段性任务，不必等待整个 G 阶段完成，也不需要每次另行询问是否记录。

固定流程：**读取状态、任务卡及相关日志 → 确定本次范围 → 实施并保留证据 → 验证 → 追加工作日志 → 同步状态与待办 → 确认完成后提交、推送并核对远程 → 交付回复**。受阻或部分完成时记录真实进展，不触发“完成后自动归档”；用户另有明确授权时按其要求执行。

- 每完成一张任务卡或一项阶段性交付，必须追加日志；同一会话完成多项任务时分别记录。任务受阻、中断或部分完成时也记录真实进展、原因与恢复条件，不写成已完成。
- 记录日期／时区、关联任务、状态、目标与范围、主要过程、修改文件、成果、验证命令与工作目录／结果、问题与现象、已尝试方法、原因判断、处理办法及效果、重要决定、遗留事项和下一步。无问题或未执行验证时明确说明，不省略状态。
- 成功、失败、纠正过程和未解决事项都要记录；区分事实、推断与待验证内容，记录方案取舍及依据。长篇输出可附阶段报告或原始记录位置，但本日志必须保留关键过程和结论，不能只留一个链接。
- 按时间顺序在文件末尾追加，使用唯一编号 `WL-YYYYMMDD-NNN`；同日多次工作递增编号。已结束记录不覆盖或删除；后续更正追加说明并引用原编号。当前未结束记录可更新为最终验证结果。
- 历史补记明确标注“补记”、补记日期和依据；缺失的时间、命令或结果标为未留存／未核实，不虚构，不把后续状态回写成历史事实。
- `worklog.md` 保存历史过程；`docs/status.md` 保存当前状态；`docs/backlog.md` 保存任务与依赖；阶段报告保存专题证据。收尾时核对它们的一致性，保留已有验收报告的历史快照。
- 日志采用中文、UTF-8 和仓库相对链接。日志义务不扩大本次实施范围，不自动授权安装或进入下一阶段；阶段性工作完成后的 Git 提交与推送按第 7 节用户持续授权执行。

新记录按以下模板展开，内容较多时使用对应的小节：

```text
## WL-YYYYMMDD-NNN｜任务名称（补记时注明）
时间／时区：实际工作日期；补记日期及依据（如适用）
关联任务与状态：Gx-Tyy／其他任务；已完成／部分完成／阻塞等
背景、目标与范围：本次要解决什么，边界是什么
工作过程：按执行顺序记录操作、调查、尝试和决定
成果与修改文件：文件路径、实现内容、交付物与证据入口
验证：工作目录、关键命令、退出码、预期与实际结果；未验证项及原因
问题与解决办法：现象、原因判断、失败尝试、修复措施、复查结果；未解决项明确标注
重要决定与影响：采用方案及依据，对后续任务的影响
遗留事项与下一步：风险、归属任务、恢复条件或下一次最小验证
```
