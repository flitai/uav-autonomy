# G2 实施方案：Windows 原生 UxAS

日期：2026-09-18，Asia/Shanghai。**G2-T01、T02 已完成，T03 可执行、尚未启动。** 原生工具链和固定依赖的源码重建、功能、路径、来源及故障检查通过，详见 [T01 记录](g2-cpp-toolchain-validation.md)与 [T02 记录](g2-dependencies-validation.md)。本文是实施方案，不是 UxAS 构建或运行验收报告；完整任务卡见 [backlog](backlog.md#4-g2-顺序与任务卡)，当前进度见 [status](status.md)，过程见 [worklog](../worklog.md)。

## 1. 目标、输入与边界

G2 的通过条件是：从干净输出目录构建 Windows 原生 `uxas.exe`，HelloWorld 两个服务通过实际内部消息总线收发 `KeyValuePair`，并正常退出。七张任务卡按 T01 → T07 顺序推进，一次一个主要实现任务。

本方案编制时只落地文档，未安装、构建或运行；该历史边界不代替后续任务授权。T01、T02 已按用户授权完成原生工具和第三方依赖验收；LMCP 与 UxAS 构建仍待后续任务。AMASE↔UxAS 的 WaterwaySearch 双向闭环归 G3；网关、Cesium、Ada、实机接入、训练集成与完整重连不纳入 G2。

2026-09-18 方案细化时的只读复核结果（工具安装前的历史快照）：

| 项目 | 已核查事实 | G2 使用约束 |
| --- | --- | --- |
| 工作区 | 起点 `0e9da36ea97d447f178bfdedd5e04f4b6a5b53e2`，`git status --short` 无输出；G1-T05 已归档 | 实施任务开始时重查，不沿用规划时“尚未提交”的旧快照 |
| 工具 | PATH 未找到 cmake、ninja、cl、MSBuild、vcpkg；常见 Visual Studio／CMake 安装目录及 vswhere 不存在 | 只表示上述范围内未发现；T01 再核查实际安装和版本 |
| 消息 | 批次 `g1-t03-20260917-152214-037296` 的 588 个 C++ 相关文件与 generation-info.json 的 SHA-256 全部匹配 | 包含 186 个 `.cpp`、382 个 `.h` 及其他生成文件；不代表 C++ 编译通过 |
| Java／Python | G1 已验收；本轮实际 Python 版本命令为 3.14.7，退出 0 | 复用 [G1 消息库验收](g1-lmcp-validation.md) 的统一输入和样本 |
| 构建与示例 | 原 Makefile 使用 C++11，包含 resources 下的 AutomationDiagramDataService；HelloWorld 配置运行 10 秒，周期为 1000／5001 ms | 保留必需源码和原示例参数，不能只编译一个独立演示程序替代 UxAS |

源码依据：[Makefile](../OpenUxAS/Makefile)、[Anod 配方](../OpenUxAS/infrastructure/specs/uxas.anod)、[HelloWorld 配置](../OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml)、[服务实现](../OpenUxAS/src/cpp/Services/01_HelloWorld.cpp)和 [UxAS 主入口](../OpenUxAS/src/cpp/UxAS_Main.cpp)。上游精确版本未知的问题沿用 G0 的本地基线与输入哈希，不扩大为无边界追溯任务。

## 2. 已确定的技术方案

### 工具链与编译约定

- Windows 11 x64，MSVC Build Tools 2022／v143、Windows SDK、CMake 3.31 系列；主工程使用 Visual Studio 2022 生成器，验收 Release x64；Ninja 供 vcpkg 相关构建使用。T01 从官方来源核实并锁定具体补丁版本、组件、校验值和实际路径，本方案不预填未验证的安装结果。
- MSVC／SDK 使用官方安装机制并记录组件及安装影响；可独立管理的 CMake、Ninja、vcpkg 和下载缓存放入被忽略的 `.tools/`。构建入口仅设置进程环境，不永久修改 PATH，不要求父终端预先启用开发环境。
- 保留源码的 C++11 兼容目标；MSVC 明确使用 `/std:c++14`，不引入对更新语言特性的业务依赖。该工具链没有 C++11 标准模式，不能将编译参数记为 `/std:c++11`。[MSVC 官方说明](https://learn.microsoft.com/en-us/cpp/build/reference/std-specify-language-standard-version?view=msvc-170)
- 第三方库静态链接，CRT 动态链接；主工程、LMCP 与依赖统一 Release `/MD`。以 `x64-windows-static-md` 的链接约定建立固定工具集的 overlay triplet，记录 SDK 和运行库来源。Debug 不作为 G2 必须交付的构建配置。
- CMake 3.31 是本轮兼容基线；现有生成模板声明最低版本 3.0，CMake 4.0 已移除低于 3.5 的策略兼容，不能无记录换用新版 CMake 或手改生成目录。[生成模板](../LmcpGen/src/templates/cpp/CMakeLists.txt)、[CMake 4.0 变更](https://cmake.org/cmake/help/v4.0/release/4.0.html)

### vcpkg 与依赖版本

用户已选择 vcpkg manifest 模式。固定 vcpkg checkout 提交、工具版本和 registry baseline；能从版本库取得的历史包通过 overrides 固定，缺失版本及本地补丁通过 overlay ports 提供。overlay 优先于 registry 解析，其源码校验值、配方、补丁、port-version 和 triplet 必须一并入库，不能认为 baseline 已锁住 overlay。不得使用浮动分支、自动更新 baseline 或全局 `vcpkg integrate install` 作为项目构建前提。[版本控制](https://learn.microsoft.com/zh-cn/vcpkg/users/versioning)、[端口解析](https://learn.microsoft.com/en-us/vcpkg/concepts/package-name-resolution)

| 依赖 | 初始版本 | 必须保留或核查的内容 |
| --- | --- | --- |
| libzmq | 4.3.1 | 内部总线和 TCP 所需功能、静态链接宏及 Windows 系统库 |
| cppzmq | 4.2.2 | 现有包装代码使用的旧 API，与 libzmq 配套验证 |
| CZMQ | 4.0.2 | TCP 收发仍使用 `zframe_*`；关闭 Zyre 不会移除该依赖 |
| pugixml | 1.12.1＋本地补丁 | `as_int64` 的实际接口、实现及大整数／缺省值行为；HelloWorld 本身调用此接口 |
| Boost | 1.74.0 | filesystem、system、regex、date_time 及其实际传递依赖 |
| SQLite | 3.39.4 | `SQLITE_ENABLE_COLUMN_METADATA`，版本与实际库一致 |
| SQLiteCpp | 1.3.1 | 使用上述外部 SQLite，关闭原配方的 Python 2 cpplint 要求 |

这些版本来自 [repositories.yaml](../OpenUxAS/infrastructure/specs/config/repositories.yaml)、[Boost 配方](../OpenUxAS/infrastructure/specs/boost.anod)、[SQLite 配方](../OpenUxAS/infrastructure/specs/sqlite.anod)与 [SQLiteCpp 配方](../OpenUxAS/infrastructure/specs/sqlitecpp.anod)。T02 已在 MSVC 下完成该组合的构建与功能验收，Boost 保留历史模块 ports，必要兼容修复见 [报告](g2-dependencies-validation.md)。后续需要改变主要依赖版本时，提交最小复现、已尝试方案和影响说明后调整任务，不顺带整体升级。

### UxAS 源码与可选桥

- 对照原 Makefile 显式整理源码集合，包含任务服务、规划代码和 [AutomationDiagramDataService](../OpenUxAS/resources/AutomationDiagramDataService)。服务注册对象必须进入最终可执行文件，不能因拆成静态库后被链接器省略。
- TCP、PUB/PULL、SUB/PUSH 等现有通信保留；[TCP 收发实现](../OpenUxAS/src/cpp/Communications/ZeroMqAddressedAttributedMessageTcpReceiverSender.cpp)使用 CZMQ，必须保留其构建及链接。
- Windows CMake 提供 `UXAS_ENABLE_ZYRE`、`UXAS_ENABLE_SERIAL`，默认 OFF；同时处理源文件、头文件、包装工具及 [桥管理器](../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkBridgeManager.cpp)的实例化分支。原源码保留，原 Makefile 默认行为不随本轮选项改变。
- 配置请求未编入的桥时明确报错并返回失败，不静默跳过后继续宣称启动成功。T04 实现并静态核查拒绝路径，T06／T07 用真实可执行文件验证。
- Zyre／串口的启用构建和运行验收另列延期事项；本轮不宣称 ON 组合可用。Windows 默认配置应无需获取这两项可选依赖。

## 3. 任务顺序与拟建接口

| 任务 | 独立交付 | 通过依据 |
| --- | --- | --- |
| G2-T01 | 锁定工具链与进程环境入口 | C/C++ 探针编译、链接、运行成功，确认 x64 和真实版本 |
| G2-T02 | vcpkg 清单、配方及依赖产物 | 全部必需依赖和功能探针通过，来源及链接一致 |
| G2-T03 | C++ LMCP 库及跨语言探针 | 七模型完整编译，原始 LMCP 字节和字段与既有样本一致 |
| G2-T04 | UxAS CMake 构建图与可选桥开关 | 配置生成成功，源码／服务集合完整，依赖与排除项可审查 |
| G2-T05 | Windows 平台适配与候选 uxas.exe | 干净输出完整编译、链接成功，构建来源完整 |
| G2-T06 | HelloWorld 运行入口与真实证据 | 双向收发、原时长运行、正常退出和日志归属通过 |
| G2-T07 | 复验、正式产物与 G3 交接 | 路径／故障矩阵及连续三次正常启停通过，证据齐全 |

以下是拟建接口和输出约定，本次未创建实现，不属于当前标准命令：

- 根级 CMake／presets 描述 LMCP、UxAS 和必要验证目标；C++ LMCP 目标在 T03 建立，UxAS 目标在 T04 接入，避免两个任务重复建设互不一致的构建入口。
- 根级 vcpkg 清单及配置描述 baseline、overrides、overlay ports／triplet；具体锁定值在 T01／T02 的有限验证后写入。工具和依赖实际使用的 CMake／Ninja 也要核对，不允许隐式下载另一版本后仍记录为 T01 版本。
- Windows 工具准备、依赖构建、LMCP 构建、UxAS 构建、运行和验收入口按任务创建；路径以脚本自身位置为基准，显式工作目录并传播失败退出码。入口名称和可复制命令在实际验证后加入使用说明。
- 输入关联 G1 统一生成目录及 generation-info.json，过期或哈希不符时阻断并走统一生成入口。需要修改生成器／模板时统一重新生成三种语言并复验受影响的 G1 链路，不混用不同批次产物或改写历史验收记录。
- 构建及候选位于 `out/build/<component>/<run-id>/`，每次配置、日志、样本和结果位于 `out/runs/<run-id>/`。验收合格的 C++ 库拟发布到 `out/artifacts/lmcp/cpp/`，与 G1 的父级来源清单通过批次关联而不覆盖；UxAS 正式产物拟发布到 `out/artifacts/uxas/`，T07 验收前仅作为候选。
- 新增接口限定为构建、环境、启动、验收及可选桥选项。LMCP／MDM 消息契约、AMASE 网络接口和任务算法保持原语义。

## 4. 验收与证据

| 层次 | 必须验证 | 不能替代的后续验证 |
| --- | --- | --- |
| 工具链与依赖 | x64 编译运行；cppzmq／CZMQ 帧；pugixml 大整数与缺省值；Boost 文件／正则／时间；SQLiteCpp 读写及列元数据 | 不代表 UxAS 构建通过 |
| C++ LMCP | 七模型完整编译；既有普通／大 ID 状态、列表、时间和 UXTASK 8 样本；校验错误及旧版本识别 | 只比较原始 LMCP；Java Sentinel 外层按已有方式剥离，不代表网络双向兼容 |
| UxAS 构建 | 干净输出构建候选；实际源文件、服务注册、静态库、CRT、系统库和平台修复可追溯 | 不代表规划任务执行通过 |
| HelloWorld | 原配置 10 秒、1000／5001 ms；两个不同服务各至少收到一条来自对方的 KeyValuePair，ID 和文本对应；正常退出 0 | 不要求精确周期或精确条数，不以启动日志或自己收到自己的消息充数 |
| 复验 | 独立干净输出重建；连续三次正常启停；其他工作目录；中文空格路径构建与运行；运行库来源检查 | 第二个干净部署环境与断网演示归 G8 |
| 故障 | 依赖缺失／损坏、生成来源不符、配置缺失／损坏、请求关闭的桥、运行超时 | 隔离副本注入；失败记录不得改为 passed，不覆盖旧合格产物 |

HelloWorld 以原 `RunDuration_s` 完成运行，验收入口设置 30 秒进程超时；超时或强制终止只能作为失败收尾。默认示例没有外部 TCP 桥，不额外占用 AMASE 示例端口；后续实际启用监听时显式配置并核查归属与释放。

每项证据保存源码基线及工作区差异、工具和依赖版本、MDM／生成器／生成库哈希、配置、命令、工作目录、退出码、stdout／stderr、消息统计和失败诊断。原始记录放在忽略目录，阶段报告必须保留可复现命令和关键结论，不能只链接本机原始日志。

## 5. 停止条件、回退与阶段收尾

- 工具或依赖来源不可确认，必须改变主要依赖版本、消息语义、任务算法或删除必需服务才能继续时，先形成最小复现、有限尝试和影响说明；不改用 WSL 结果替代 Windows 验收。
- 按项目约定限制单次探索窗口，遇阻记录恢复条件和下一次最小实验。普通平台兼容修复在已授权任务内继续，重大范围变化另行调整任务。
- 保留原上游目录、示例、旧库和失败证据。回退只处理本任务修改、归属清晰的输出与进程；不自动卸载共享工具、不清空用户缓存、不以宽泛进程名结束其他实例。
- 每张任务卡收尾先验证，再追加 worklog、同步 status／backlog；T01～T07 全部通过才登记 G2 完成。文档细化完成不计作任何 G2 实现卡完成。
- G3 接收合格 UxAS、同批 LMCP 和既有 AMASE、必要服务／桥清单及启动配置约定；继续验证 Sentinel／属性封装、来源过滤、启动顺序、实时状态和真实规划命令执行。
- 完整任务边界和状态以 [七张任务卡](backlog.md#4-g2-顺序与任务卡)为准；Zyre／串口启用支持进入延期事项，G3～G8 保留轮廓。本次不自动提交或推送。
