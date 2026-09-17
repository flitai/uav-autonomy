# uav-autonomy：AI 开发协作说明

适用范围：本仓库及其子目录。最后核对日期：2026-09-17。

这是项目级工作约定。遵循当前会话中更高优先级的指令和用户明确要求；修改子目录前检查是否还有适用于该目录的说明。源码、构建配置和实际运行结果用于判断工程事实，规划文档不代表功能已实现。

## 1. 项目目标与当前状态

本项目基于 LmcpGen、OpenAMASE、OpenUxAS，建设无人系统任务级仿真与自主策略研发环境。

当前改造方向：

1. 补齐 Windows 原生构建、启动、运行和部署能力。
2. 保留 OpenAMASE 仿真内核和 OpenUxAS 自主任务服务。
3. 新增消息网关，以 CesiumJS 三维 GIS 逐步替换原有态势可视化与操作界面。
4. 后续为 TorchRL／BenchMARL 训练集成复用协议与仿真控制接口。

截至上述核对日期，G0 基线与环境清点已完成，证据见 [G0 报告](docs/g0-baseline.md)。G1 尚未启动，需先准备 Java 构建环境；Git 和实际 Python 3.14.7 运行时已验证可用，项目依赖兼容性未验证。尚未完成本机编译和联调，也未落地统一 Windows 构建链、Cesium 前端、消息网关或训练集成。继续工作时先读 [当前状态](docs/status.md) 与 [任务清单](docs/backlog.md)，并重新检查实际环境，不把历史快照当成永久结论。

Windows 原生运行是目标；WSL／Linux 可作参考或过渡环境，其验证结果必须单独标注。总体计划已确定首期默认 Windows 11 x64、联网开发与指定场景的基础离线演示，并保留原场景编辑器；实体规模和具体地理资源按任务细化。CMake／MSVC、Python 网关等是当前计划中的候选实现，不是已经验证的工具链。

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

改造初期保留三个现有源码目录的位置。计划中的 `src/sim_bridge/`、`apps/gis_gateway/`、`apps/cesium_viewer/`、`scripts/windows/`、根级 CMake 等，需要在对应任务中实际创建；引用前先确认存在。

## 3. 开始任务时

1. 明确本次要求是分析、文档、实现、修复还是验证，只完成授权范围内的工作。
2. 运行 `git status --short`，识别用户现有修改和未跟踪文件；保留与本次任务无关的内容。
3. 检查适用的目录说明，阅读目标组件 README、实际构建配置及相关源码；优先用 `rg` 定位。
4. 根据任务按需阅读项目文档，不必每次加载全部长文：
   - [当前状态](docs/status.md)、[任务清单](docs/backlog.md)：当前关卡、缺口、下一任务及验收条件；历史基线见 [G0 报告](docs/g0-baseline.md)。
   - [工作日志](worklog.md)：先读最近记录及当前任务关联的问题、尝试和决定，避免重复排查；新记录按第 10 节要求追加。
   - [总体实施计划与阶段验收](04.项目总体实施计划与阶段验收.md)：按用户主导、AI 逐项实施的方式推进，G0～G8 为任务细化与验收依据；首期采用联网开发、基础离线演示。
   - [目录分析与 Windows／Cesium 改造计划](03.项目目录分析与Windows_Cesium改造计划.md)：目录、技术方案及改造风险的参考。
   - [团队实施技术建议书与资源清单](02.OpenAMASE_OpenUxAS_TorchRL_BenchMARL_团队实施技术建议书与资源清单.md)：仿真与训练的长期设计。
   - [思路与技术途径参考](01.无人自主智能策略研发_思路与技术途径参考.md)：研究背景与目标。
5. 检查所需工具是否真实可用。`PATH` 未找到命令只代表当前会话未找到；WindowsApps 的 Python 入口也不能代替解释器可用性检查。
6. 选择能验证本次修改的最小闭环。对已明确且可逆的任务继续执行；缺少会影响架构或验收的必要信息时，说明具体问题，同时推进不依赖答案的工作。

默认使用中文沟通和编写项目说明，代码标识符沿用现有语言和命名习惯。区分“源码确认”“实际执行通过”“推测／待验证”，不将计划或静态阅读写成运行结果。

## 4. 构建与运行入口

以下是根据现有工程整理的入口，**不表示命令已在当前设备验证通过**。先核对依赖，再逐条执行并检查退出码；构建步骤失败后不要继续使用旧产物冒充成功。

### Windows：Java 工程

工作目录为仓库根目录，使用 PowerShell：

```powershell
# LmcpGen 当前源码级别为 Java 8；AMASE 为 Java 11。
# 先确认所选 JDK 和 Ant 能同时满足两个工程。
java -version
javac -version
ant -version

ant -f .\LmcpGen\build.xml jar
ant -f .\OpenAMASE\OpenAMASE\build.xml jar
```

预期主要产物为 `LmcpGen/dist/LmcpGen.jar` 和 `OpenAMASE/OpenAMASE/dist/OpenAMASE.jar`。上面的 AMASE 构建会使用其当前配置的消息库；做组件联调前，必须核对并接入统一生成的 Java LMCP 库。

消息代码生成示例，工作目录同样为仓库根目录：

```powershell
java -jar .\LmcpGen\dist\LmcpGen.jar -mdmdir .\OpenUxAS\mdms -cpp -dir .\out\generated\lmcp\cpp
java -jar .\LmcpGen\dist\LmcpGen.jar -mdmdir .\OpenUxAS\mdms -java -dir .\out\generated\lmcp\java
java -jar .\LmcpGen\dist\LmcpGen.jar -mdmdir .\OpenUxAS\mdms -py -dir .\out\generated\lmcp\py
```

`out/generated/lmcp/` 是后续消息生成的约定输出位置，不是已存在的构建集成。首次生成或构建前由 G1-T01 落实精确忽略规则及 Ant 默认输出的处理；生成源码之后还需构建相应库并配置消费者路径。

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
- AMASE 的 TCP 服务读写原始 LMCP；当前 UxAS TCP 桥使用属性消息及 Sentinel 封装。直接连接存在兼容风险，必须用实际双向消息验证，不能以端口连通替代。
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
- 不覆盖无关用户修改，不自动提交或推送；用户已明确要求的版本管理操作按其授权执行。

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

每次阶段性任务收尾，先按第 10 节追加根级 `worklog.md` 并同步相关状态，再给出交付回复；工作日志是任务交付的一部分。回复简要说明：改了什么、主要文件、实际验证结果、剩余限制。重大接口或构建入口改变时同步更新相关说明，避免后续 AI 使用过期信息。

## 9. 本说明的维护

`AGENTS.md` 是完整规范的唯一维护入口，`CLAUDE.md` 引用本文件。只记录稳定的项目约定与可核查事实；临时故障、单次任务日志、长篇调研放入对应文档，不持续堆积在本文件中。

完成 Windows 构建、网关或 Cesium 集成后，更新当前状态、标准命令及验证入口。规划中的目录或能力只有在实际落地后才能改写为“已有”。

## 10. 固定工作流程与工作日志

根目录 [worklog.md](worklog.md) 是固定、持续追加的工作日志。此约定来自用户明确要求，适用于后续分析、规划、实现、修复、验证和文档类阶段性任务，不必等待整个 G 阶段完成，也不需要每次另行询问是否记录。

固定流程：**读取状态、任务卡及相关日志 → 确定本次范围 → 实施并保留证据 → 验证 → 追加工作日志 → 同步状态与待办 → 交付回复**。

- 每完成一张任务卡或一项阶段性交付，必须追加日志；同一会话完成多项任务时分别记录。任务受阻、中断或部分完成时也记录真实进展、原因与恢复条件，不写成已完成。
- 记录日期／时区、关联任务、状态、目标与范围、主要过程、修改文件、成果、验证命令与工作目录／结果、问题与现象、已尝试方法、原因判断、处理办法及效果、重要决定、遗留事项和下一步。无问题或未执行验证时明确说明，不省略状态。
- 成功、失败、纠正过程和未解决事项都要记录；区分事实、推断与待验证内容，记录方案取舍及依据。长篇输出可附阶段报告或原始记录位置，但本日志必须保留关键过程和结论，不能只留一个链接。
- 按时间顺序在文件末尾追加，使用唯一编号 `WL-YYYYMMDD-NNN`；同日多次工作递增编号。已结束记录不覆盖或删除；后续更正追加说明并引用原编号。当前未结束记录可更新为最终验证结果。
- 历史补记明确标注“补记”、补记日期和依据；缺失的时间、命令或结果标为未留存／未核实，不虚构，不把后续状态回写成历史事实。
- `worklog.md` 保存历史过程；`docs/status.md` 保存当前状态；`docs/backlog.md` 保存任务与依赖；阶段报告保存专题证据。收尾时核对它们的一致性，保留已有验收报告的历史快照。
- 日志采用中文、UTF-8 和仓库相对链接。日志义务不扩大本次实施范围，不自动授权安装、进入下一阶段或 Git 提交。

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
