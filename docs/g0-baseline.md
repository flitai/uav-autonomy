# G0 基线、环境与验收报告

核查日期：2026-09-17（Asia/Shanghai，UTC+08:00）。状态：**G0 已完成；G1 尚未启动，需先准备 Java 构建环境。**

本报告对应[总体实施计划](../04.项目总体实施计划与阶段验收.md)的 G0-T01～T04。执行范围为本地只读检查和文档整理；未安装依赖、生成消息代码、构建、启动仿真或自动提交 Git。状态入口见 [status.md](status.md)，执行任务卡见 [backlog.md](backlog.md)。

## 1. 源码与工作区基线

开始核查时间：2026-09-17T09:23:17+08:00。根仓库分支为 `main`，根提交为 `061685f7f2e9d17c2c9eb0434a309a3d66c3e648`，提交说明为 `init`。远程 `origin` 的 fetch／push 地址均为 `git@github.com:flitai/uav-autonomy.git`；本次未联网查询或拉取。

| 源码目录 | 根提交下的 Git tree 标识 | 已跟踪文件数 | 精确上游提交 |
| --- | --- | --- | --- |
| `LmcpGen/` | `5a03ccc3bead5fdbb98922a96d4e84fbfbf69c68` | 220 | 未知 |
| `OpenAMASE/` | `bd19bf511bc3c0198654d575c6c0d0af9c0532bc` | 1030 | 未知 |
| `OpenUxAS/` | `b965241ff917c40fb5c1cfae6f32035295eeaee7` | 2536 | 未知 |

三个目录均为普通源码树（Git 模式 `040000`），没有各自的 `.git`，根目录没有 `.gitmodules`。连同根级 `.gitattributes`，全库已跟踪文件共 **3787** 个。根提交及 tree 标识固定本地内容，不能冒充三个项目的上游 SHA；Anod 中的分支名也不能用于反推该 SHA。

开始时已跟踪文件无改动；以下六份用户已有文件均未跟踪：

- `01.无人自主智能策略研发_思路与技术途径参考.md`
- `02.OpenAMASE_OpenUxAS_TorchRL_BenchMARL_团队实施技术建议书与资源清单.md`
- `03.项目目录分析与Windows_Cesium改造计划.md`
- `04.项目总体实施计划与阶段验收.md`
- `AGENTS.md`
- `CLAUDE.md`

G0 新增本目录的三份文档，更新总体计划与 AGENTS 的状态和索引；01～03 及 CLAUDE 保持原内容。CLAUDE 已导入 AGENTS，无需复制维护第二套状态。上述文件仍未提交，文档交付不等于已创建 Git 提交。

核查时根级 `.gitignore`、`OpenUxAS/.gitignore`、`docs/`、`out/`、`scripts/windows/` 均不存在；本阶段只创建 `docs/` 及三份文档。未发现约定位置的 `LmcpGen/dist/LmcpGen.jar`、`OpenAMASE/OpenAMASE/dist/OpenAMASE.jar`、`OpenUxAS/obj/cpp/uxas` 或 `OpenUxAS/build/uxas.exe`。这不等同于扫描了磁盘上的所有可能产物。

## 2. 环境核查

环境核查时间：2026-09-17T09:23:18+08:00。Windows 11 Professional x64，DisplayVersion `25H2`，构建号 `26200`；PowerShell `5.1.26100.9444`。当前会话未设置 `JAVA_HOME`、`ANT_HOME`、`VCPKG_ROOT`。

| 工具 | 实际路径／发现情况 | 实际执行与结论 | 后续归属 |
| --- | --- | --- | --- |
| Git | `C:/Program Files/Git/cmd/git.exe` | `git version 2.55.0.windows.3`；退出码 0，可运行 | 已满足 G0 |
| Python 运行时 | `%LOCALAPPDATA%/Python/pythoncore-3.14-64/python.exe` | 实际执行得到 3.14.7、64 位、退出码 0；项目依赖兼容性未验证 | G1-T03／T05 |
| Python 入口 | WindowsApps 的 `python.exe`、`py.exe`；`%LOCALAPPDATA%/Python/bin/python.exe` | 仅发现入口；可用性结论来自上一行真实解释器，不来自入口 | 不单独计为就绪 |
| Java／javac／Ant | PATH 与下述补充范围内未发现 | 没有执行版本或构建检查，不能认定整机未安装 | G1-T01 |
| CMake／Ninja／cl／MSBuild | PATH 与下述补充范围内未发现 | C++ 工具链尚未验证 | G2 |
| Node／npm | PATH 与下述补充范围内未发现 | 前端工具链尚未验证 | G5 |

Python 关键输出为 `3.14.7 (tags/v3.14.7:823f032, Aug 5 2026, 10:51:32) [MSC v.1944 64 bit (AMD64)]`，实际解释器位于当前用户的 LocalAppData。输出中的 MSC 是构建 Python 的编译器信息，并不证明本机装有 MSVC。未创建 Python 环境或尝试安装项目依赖。

查找范围：

- `Get-Command -All`：git、python、py、java、javac、ant、cmake、ninja、cl、msbuild、node、npm。
- 常见位置：Program Files 下的 Java、Eclipse Adoptium、Microsoft/jdk-11、CMake、nodejs、Microsoft Visual Studio；Program Files (x86) 下的 Microsoft Visual Studio 及其 Installer/vswhere.exe；`C:/Tools`、`E:/Tools`、`E:/Software`、`C:/ProgramData/chocolatey/bin`、`%USERPROFILE%/scoop/apps`。本次这些路径均未发现。
- Program Files、Program Files (x86)、LocalAppData/Programs 的一级目录按工具名称筛查；另查 LocalAppData/Python。名称中的 Antigravity 不视为 Apache Ant。
- HKLM 的 Uninstall、WOW6432Node/Uninstall 和 HKCU 的 Uninstall 注册表项按 Java／JDK／Python／CMake／Ninja／Apache Ant／Node.js／Visual Studio／Build Tools 等名称筛查；匹配到 Python 3.14.7 和 VS Code 1.138.0，VS Code 不是 C++ Build Tools。

以上是限定范围的发现结果，没有做整盘穷举。缺少工具不阻止 G0 通过，但阻止对应构建任务通过验收。

## 3. 消息模型与依赖

### 3.1 统一消息输入

统一输入目录为 [OpenUxAS/mdms](../OpenUxAS/mdms)。七个 XML 均成功解析并读取 SeriesName／Version；这是 XML 结构读取结果，尚未运行 LmcpGen 的语义检查、代码生成或跨语言测试。

| 文件 | 系列 | 版本 | 本轮验证 |
| --- | --- | --- | --- |
| `OpenUxAS/mdms/CMASI.xml` | CMASI | 3 | XML 解析通过 |
| `OpenUxAS/mdms/IMPACT.xml` | IMPACT | 14 | XML 解析通过 |
| `OpenUxAS/mdms/PERCEIVE.xml` | PERCEIVE | 1 | XML 解析通过 |
| `OpenUxAS/mdms/ROUTE.xml` | ROUTE | 4 | XML 解析通过 |
| `OpenUxAS/mdms/UXNATIVE.xml` | UXNATIVE | 9 | XML 解析通过 |
| `OpenUxAS/mdms/UXTASK.xml` | UXTASK | 8 | XML 解析通过 |
| `OpenUxAS/mdms/VEHICLES.xml` | VEHICLES | 1 | XML 解析通过 |

后续顺序：准备 JDK／Ant → 从本地 LmcpGen 构建生成器 → 从上述同一组 MDM 生成 Java／C++／Python → 编译 Java 消息库 → 显式接入 AMASE → 实际状态接收。C++ 消息库的编译归 G2。生成器、输入与输出哈希需要一并保存，不能只记录“生成成功”。

[LmcpGen 配置](../LmcpGen/nbproject/project.properties)声明 Java 8 源码级别，[AMASE 配置](../OpenAMASE/OpenAMASE/nbproject/project.properties)声明 Java 11。G1 先准备 JDK 11 兼容基线及 Ant；具体发行版、补丁版本、来源及校验值在 G1-T01 固定，G0 不代替兼容性试验。

### 3.2 Anod 声明的依赖与来源

下表来自本地 [repositories.yaml](../OpenUxAS/infrastructure/specs/config/repositories.yaml)、[Boost 配方](../OpenUxAS/infrastructure/specs/boost.anod)和 [SQLite 配方](../OpenUxAS/infrastructure/specs/sqlite.anod)。它们是**仓库声明值**，本次未下载、构建或检查网络可达性，也未验证 Windows 兼容性。

| 组件 | 仓库声明版本／引用 | 配方声明来源 |
| --- | --- | --- |
| OpenAMASE | master（浮动分支） | https://github.com/afrl-rq/OpenAMASE.git |
| LmcpGen | develop（浮动分支） | https://github.com/afrl-rq/LmcpGen.git |
| OpenUxAS | revision: None；vcs: external | 当前目录 `.` |
| cppzmq | v4.2.2 | https://github.com/zeromq/cppzmq.git |
| czmq | v4.0.2 | https://github.com/zeromq/czmq.git |
| libzmq | v4.3.1 | https://github.com/zeromq/libzmq.git |
| pugixml | v1.12.1，另有本地补丁 | https://github.com/zeux/pugixml.git |
| serial | 1.2.1，另有本地补丁 | https://github.com/wjwwood/serial.git |
| SQLiteCpp | 1.3.1 | https://github.com/SRombauts/SQLiteCpp.git |
| zyre | v2.0.0 | https://github.com/zeromq/zyre.git |
| Boost | 1.74.0 | https://archives.boost.io/release/1.74.0/source/boost_1_74_0.tar.bz2 |
| SQLite | sqlite-autoconf-3390400（3.39.4） | https://sqlite.org/2022/sqlite-autoconf-3390400.tar.gz |
| zeromqada | master（浮动分支） | https://github.com/persan/zeromq-Ada.git |

Boost 配方列出的组件为 filesystem、system、regex、date_time，并采用 GCC／C++11 相关配置；现有 UxAS Makefile 也是 C++11。CMake／编译器配方可读取 `OPENUXAS_CMAKE_VERSION`／`OPENUXAS_COMPILER_VERSION`，不能据此说 Windows 工具版本已锁定。Ada 不纳入首期 C++ 移植。

[pugixml 补丁](../OpenUxAS/infrastructure/specs/patches/pugixml.patch)与 int64 支持有关；[serial 补丁](../OpenUxAS/infrastructure/specs/patches/serial.patch)移除 catkin 依赖并调整安装路径。G2 锁定依赖时必须核对补丁效果，不能只替换成同名同版本软件包。

Anod 可能使用 `OpenUxAS/develop/` 下的源码或沙箱中另外检出的 AMASE／LmcpGen。G1 默认从当前工作区的兄弟目录构建；若调用 Anod，先记录实际解析的源码路径和版本，不能将其产物默认归入本报告的本地基线。

### 3.3 AMASE 随库 Java 依赖

依据 [project.properties](../OpenAMASE/OpenAMASE/nbproject/project.properties) 与 [nblibraries.properties](../OpenAMASE/OpenAMASE/lib/nblibraries.properties)，当前编译／打包涉及的以下六个 JAR 路径均存在，已计算 SHA-256。存在文件不等于版本兼容或可以加载。

| 相对 OpenAMASE/OpenAMASE/lib 的路径 | 静态结论 |
| --- | --- |
| `lmcplib.jar` | 随库消息库；与七个当前 MDM 的一致性未验证 |
| `worldwind.jar` | 文件名未标版本，实际版本与运行兼容性待核查 |
| `Flexdock/flexdock-1.2.3.jar` | 文件名标注 1.2.3 |
| `SwingX/swingx-all-1.6.4.jar` | 文件名标注 1.6.4 |
| `GRAL/gral-core-0.10.jar` | 文件名标注 0.10 |
| `CopyLibs/org-netbeans-modules-java-j2seproject-copylibstask.jar` | NetBeans Ant 打包任务，文件名未标版本 |

其他库声明不等于当前有效编译依赖；本次未对全部 JAR 做类加载或运行检验。G1-T03／T04 应比较随库 LMCP 与统一生成版本，并确认 AMASE 实际 classpath，避免同时加载两套同名消息类。

## 4. 示例、工作目录与端口

### 4.1 HelloWorld 与 WaterwaySearch

[HelloWorld/config.yaml](../OpenUxAS/examples/01_HelloWorld/config.yaml)引用同目录的 [cfg_HelloWorld.xml](../OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml)。配置的 EntityID 为 100，RunDuration_s 为 10.0，两个 HelloWorld 服务周期分别为 1000 ms 和 5001 ms。这是 G2 的最小 UxAS 入口，不依赖 AMASE；本次未运行。

[WaterwaySearch/config.yaml](../OpenUxAS/examples/02_Example_WaterwaySearch/config.yaml)引用同目录的 [cfg_WaterwaySearch.xml](../OpenUxAS/examples/02_Example_WaterwaySearch/cfg_WaterwaySearch.xml)、[Scenario_WaterwaySearch.xml](../OpenUxAS/examples/02_Example_WaterwaySearch/Scenario_WaterwaySearch.xml)，运行目录声明为 `RUNDIR_WaterwaySearch`。场景时长配置为 785.0 秒，实体 ID 为 400 和 500；这不是实测运行时长。

UxAS 的 SendMessagesService 使用 `PathToMessageFiles="../MessagesToSend/"`。以下六个相对该目录的引用全部存在、可解析为 XML，并已取哈希：

| 消息文件 | 配置发送时刻（ms） | XML 根类型 |
| --- | --- | --- |
| `AirVehicleConfiguration_V400.xml` | 200 | AirVehicleConfiguration |
| `AirVehicleConfiguration_V500.xml` | 200 | AirVehicleConfiguration |
| `AirVehicleState_V400.xml` | 250 | AirVehicleState |
| `AirVehicleState_V500.xml` | 250 | AirVehicleState |
| `tasks/1000_LineSearch_LINE_Waterway_Deschutes.xml` | 300 | LineSearchTask |
| `tasks/1001_AutomationRequest_LINE_Waterway_Deschutes.xml` | 5000 | AutomationRequest |

原相对路径依赖“示例目录下的运行目录”这一关系。改用 `out/runs/` 时必须在 G1／G2 启动任务中处理资源绝对路径或运行配置副本，并保存实际配置；不能直接迁移工作目录后照用旧路径。

[AMASE Common.bat](../OpenAMASE/OpenAMASE/run/win/Common.bat)使用当前目录、相对跳转和旧 classpath；[旧 UxAS 启动脚本](../OpenUxAS/examples/02_Example_WaterwaySearch/runUxAS_WaterwaySearch.bat)引用 `build/uxas.exe` 并清理运行目录中的数据／日志。当前 Makefile 默认产物目录为 `obj/cpp`。这些脚本仅阅读，未执行；后续脚本应从自身位置定位资源并限制清理范围。

### 4.2 端口快照

检查时刻：**2026-09-17T09:24:26.1162377+08:00**。成功查询当前 TCP Listen 状态，下列六个端口均无监听记录。此快照不保证未来启动时仍可用。

| 端口 | 配置角色与地址 | 来源 |
| --- | --- | --- |
| 5555 | AMASE 全局 TCP 服务；UxAS 客户端连接 `tcp://127.0.0.1:5555` | AMASE Plugins.xml 与 WaterwaySearch 配置 |
| 5560 | UxAS PUB，`tcp://*:5560` | WaterwaySearch 配置 |
| 5561 | UxAS PULL，`tcp://*:5561` | WaterwaySearch 配置 |
| 9999 | UxAS 另一 TCP 服务，`tcp://*:9999` | WaterwaySearch 配置 |
| 9400 | headless EntityNetworkModule 对实体 400 的 TCP 配置 | amase_headless/EntityControl.xml |
| 9500 | headless EntityNetworkModule 对实体 500 的 TCP 配置 | amase_headless/EntityControl.xml |

实体端口仅在对应模块和实体启用时适用，不能推断所有运行模式都会监听。依据包括 [headless 插件配置](../OpenAMASE/OpenAMASE/config/amase_headless/Plugins.xml)、[实体网络配置](../OpenAMASE/OpenAMASE/config/amase_headless/EntityControl.xml)与 [EntityNetworkModule](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/entity/modules/EntityNetworkModule.java)。headless 配置存在不代表 Windows 上无界面模式已经验证。

### 4.3 地形与协议边界

仓库文件列表（含隐藏文件、排除 Git 元数据）中未发现 `.dt0`／`.dt1`／`.dt2` 文件，也未找到 `TerrainService.xml`；未扫描仓库外地形资源。G1 验证场景运行时需记录实际地形来源或缺省行为，G5 高度核对不能假定 DTED 齐全。

静态源码显示 [AMASE TcpServer](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/TcpServer.java)与 [UxAS TCP 桥](../OpenUxAS/src/cpp/Communications/LmcpObjectNetworkTcpBridge.cpp)／[属性消息收发](../OpenUxAS/src/cpp/Communications/ZeroMq/ZmqAttributedMsgSenderReceiver.cpp)存在原始 LMCP 与属性消息／Sentinel 外层封装差异。G1 的最小客户端先验证 AMASE 实际输出；AMASE ↔ UxAS 的双向兼容、来源过滤和回路检查归 G3，端口连接成功不算闭环成功。

## 5. 后续输出约定

以下目录均为后续任务的约定，**G0 未创建**：

| 用途 | 约定路径 | 使用要求 |
| --- | --- | --- |
| 消息生成代码 | `out/generated/lmcp/java/`、`cpp/`、`py/` | 同一组 MDM 与生成器输入，保存生成清单 |
| 构建中间产物 | `out/build/<component>/` | 按组件分离，记录实际构建参数 |
| 可交付产物 | `out/artifacts/<component>/` | JAR／库／可执行文件及哈希 |
| 运行记录 | `out/runs/<run-id>/` | 配置快照、命令、stdout／stderr、状态样本与元数据 |
| 临时输出 | `out/tmp/<task-id>/` | 仅清理该任务拥有的路径 |

原 Ant 默认会使用源码树中的 build／dist；G1 先验证能否覆盖输出属性，必要时明确临时例外并加入精确忽略规则，不能只把产物拷贝到 out 就声称源码树没有中间文件。根级忽略规则须在第一次构建／生成前由 G1-T01 落地，保留上游随库 JAR，不使用全局 `*.jar` 忽略。

## 6. 风险、归属与下一次验证

| 编号 | 已知事实／缺口 | 归属 | 下一次最小验证 |
| --- | --- | --- | --- |
| R01 | 三个精确上游 SHA 未知 | G0 已固定本地基线；后续上游升级任务 | 如需升级，单独比对上游与本地内容，再记录来源；不阻塞当前本地构建 |
| R02 | 限定范围内未找到 Java／Ant、C++、Node 工具链 | G1-T01；G2；G5 | 首先实际运行 java／javac／ant 并记录来源；其他工具在对应阶段准备 |
| R03 | 随库 lmcplib.jar 与当前 MDM 一致性未知 | G1-T03／T04 | 比较系列／类型版本、固定样本解码，确认 AMASE 仅加载统一库 |
| R04 | AMASE 与 UxAS TCP 外层封装存在差异 | G3；G1-T05 提供 AMASE 样本 | 抓取实际双向消息并核对外层封装、过滤及命令执行 |
| R05 | Anod 可使用另检出的组件和浮动分支 | G1-T02／T04；G2 | 构建记录包含实际源码绝对路径及本地基线；使用 Anod 前核查解析结果 |
| R06 | 旧脚本依赖工作目录、旧产物路径与清理逻辑 | G1-T04；G2；G3 | 从不同工作目录启动，确认资源解析、日志归属与退出行为 |
| R07 | 未发现根级生成物忽略规则 | G1-T01 | 生成前验证精确忽略规则，确认随库 JAR 仍受跟踪 |
| R08 | 仓库未提供已发现的 DTED；高度基准待核对 | G1-T04；G5 | 记录无地形数据时场景行为；随后用已知坐标／高程样本校核 |
| R09 | Python 3.14.7 可运行，但项目依赖未验证 | G1-T03／T05；G4 | 先导入生成消息包并解析固定样本；有证据再调整解释器或依赖 |
| R10 | 旧 C++ 依赖及本地补丁尚未在 Windows 构建 | G2 | 将版本、补丁与编译选项作为整体做最小构建验证 |

G1 任务顺序为 T01 环境 → T02 生成器 → T03 消息库 → T04 AMASE → T05 实际状态；具体输入、验收、回退与停止条件见 [backlog.md](backlog.md)。G0 不因上述缺口扩大到安装或实现。

## 7. 检查命令与关键结果

以下是本次检查所用命令的整理版，工作目录为仓库根目录，Shell 为 PowerShell 5.1。机器路径用环境变量表示；不是依赖安装／构建脚本。后续复查的时间和工作区清单应以届时输出为准。

### 7.1 Git 与文件基线

```powershell
git rev-parse HEAD
git remote -v
git ls-tree HEAD LmcpGen OpenAMASE OpenUxAS
git diff --name-only HEAD
git -c core.quotepath=false status --short --untracked-files=all
(git ls-files).Count
foreach ($dir in @('LmcpGen', 'OpenAMASE', 'OpenUxAS')) {
    [pscustomobject]@{ Directory=$dir; Tracked=(git ls-files -- $dir).Count }
}
Test-Path -LiteralPath .gitmodules
foreach ($dir in @('LmcpGen', 'OpenAMASE', 'OpenUxAS')) {
    Test-Path -LiteralPath (Join-Path $dir '.git')
}
```

结果：提交、tree 和计数见第 1 节；Git 查询成功，初始 diff 无输出，初始 status 为六项 `??`，元数据路径均为 False。交付后 status 增加本阶段三份未跟踪文档；已跟踪源码仍无改动。

### 7.2 系统、命令与实际解释器

```powershell
Get-Date -Format o
[Environment]::OSVersion.VersionString
[Environment]::Is64BitOperatingSystem
$PSVersionTable.PSVersion.ToString()
Get-ItemProperty 'HKLM:/SOFTWARE/Microsoft/Windows NT/CurrentVersion' |
    Select-Object EditionID, DisplayVersion, CurrentBuild
Get-Command git,python,py,java,javac,ant,cmake,ninja,cl,msbuild,node,npm -All -ErrorAction SilentlyContinue |
    Select-Object Name, Source
git --version
$LASTEXITCODE
$g0Python = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $g0Python -I -B -c "import sys; print(sys.version); print(sys.executable); print(sys.maxsize > 2**32)"
$LASTEXITCODE
```

结果：Git 与实际 Python 的退出码均为 0；Python 最后一项为 True。查找命令未命中的工具没有执行结果，不能把发现过程的成功当成工具可用。实际检查使用 `Test-Path -LiteralPath`／`Get-ChildItem -Directory` 检查第 2 节列明的补充目录；注册表检查方法如下：

```powershell
$g0Uninstall = @(
    'HKLM:/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/*',
    'HKLM:/SOFTWARE/WOW6432Node/Microsoft/Windows/CurrentVersion/Uninstall/*',
    'HKCU:/SOFTWARE/Microsoft/Windows/CurrentVersion/Uninstall/*'
)
Get-ItemProperty -Path $g0Uninstall -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -match 'Java|JDK|OpenJDK|Temurin|Adoptium|Python|CMake|Ninja|Apache Ant|Node.js|Visual Studio|Build Tools' } |
    Select-Object DisplayName, DisplayVersion, InstallLocation
```

注册表匹配结果为 Python 与 VS Code，不能以未匹配推断其他位置不存在工具。

### 7.3 XML、哈希、依赖与端口

```powershell
Get-ChildItem -LiteralPath OpenUxAS/mdms -Filter *.xml | ForEach-Object {
    $g0Model = [xml](Get-Content -LiteralPath $_.FullName -Raw -Encoding utf8)
    [pscustomobject]@{
        File=$_.Name
        Series=$g0Model.MDM.SeriesName
        Version=$g0Model.MDM.Version
        SHA256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    }
}
$g0Example = 'OpenUxAS/examples/02_Example_WaterwaySearch'
$g0Config = [xml](Get-Content -LiteralPath "$g0Example/cfg_WaterwaySearch.xml" -Raw -Encoding utf8)
$g0Service = $g0Config.SelectSingleNode('//Service[@Type="SendMessagesService"]')
foreach ($message in $g0Service.Message) {
    $g0File = Join-Path "$g0Example/MessagesToSend" $message.MessageFileName
    $g0Xml = [xml](Get-Content -LiteralPath $g0File -Raw -Encoding utf8)
    [pscustomobject]@{
        File=$g0File
        Exists=(Test-Path -LiteralPath $g0File)
        Root=$g0Xml.DocumentElement.Name
        SHA256=(Get-FileHash -LiteralPath $g0File -Algorithm SHA256).Hash
    }
}
rg -n 'revision:|url:' OpenUxAS/infrastructure/specs/config/repositories.yaml
rg -n 'NAME|URL|has_local_patch|patch\(' OpenUxAS/infrastructure/specs -g '*.anod'
rg --files --hidden -g '!**/.git/**' |
    Where-Object { $_ -match '\.(dt0|dt1|dt2)$|(^|[/\\])TerrainService\.xml$' }
Get-Date -Format o
Get-NetTCPConnection -State Listen -ErrorAction Stop |
    Where-Object { $_.LocalPort -in @(5555,5560,5561,9999,9400,9500) } |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

结果：7 个 MDM 与 6 个消息 XML 解析成功；MDM 版本见第 3 节，消息文件完整；地形查询无匹配；TCP 查询成功且筛选后无监听记录（时刻见第 4 节）。其他关键文件使用相同的 Get-FileHash 命令，结果见附录。XML 可解析不代表 LMCP 语义或运行行为已通过。

## 8. G0 验收

验收复核时间：2026-09-17T09:38:46.5979764+08:00。本地只读校验命令退出码为 0，关键结果如下；Markdown 校验范围为围栏闭合、表格列数及本地链接／锚点，不包含浏览器渲染测试。

```text
Documents=5; LocalLinks=61; Tables=20
VerifiedHashes=30; VerifiedModels=7; PreservedOriginalDocs=4
TrackedSourceUnchanged=True; UntrackedFiles=9; BuildOutputsCreated=False
```

| 验收项 | 结果与证据 |
| --- | --- |
| 源码提交、目录标识和文件数量可追溯 | 通过；根提交与三棵 tree、3787 个已跟踪文件已核对 |
| MDM 版本与关键哈希符合实际文件 | 通过；7 个 XML 的系列版本、附录全部 SHA-256 已复核 |
| 环境结论区分查找范围与实际运行 | 通过；只有 Git／真实 Python 标为可运行，其他工具未冒称就绪 |
| 示例引用存在，端口注明时刻 | 通过；6 个消息文件齐全，6 个端口附查询快照 |
| 文档链接、Markdown 与 UTF-8 正常 | 通过；本次新增／更新的 5 份文档完成本地链接、围栏／表格结构与严格 UTF-8 检查 |
| 工作区变更限于文档 | 通过；新增 3 份文档、更新 2 份索引，原 01～03 和 CLAUDE 内容保持不变；已跟踪源码无差异 |
| 无越界执行 | 通过；未安装、生成、构建、启动仿真或提交 Git；未创建 out／scripts/windows |
| 缺口均有后续归属 | 通过；第 6 节风险表与 backlog 任务卡已关联 |

**结论：G0 已完成。环境未全部就绪；下一任务是 G1-T01，当前停留在交接状态，不自动进入 G1。**

## 附录：关键文件 SHA-256

以下共 30 个条目，均为本次工作区原始文件字节的 SHA-256。Git tree 标识采用 Git 对象算法，不能与此表的文件哈希混用。涉及跨平台行尾变化时应重新取哈希并解释差异，不能仅据字节哈希改变推断消息语义变化。

| 仓库相对路径 | SHA-256 |
| --- | --- |
| `OpenUxAS/mdms/CMASI.xml` | `EBF4D93CD57F798CF9D4CCC5464C4BED23FD113277F7956543885897C29BF360` |
| `OpenUxAS/mdms/IMPACT.xml` | `EF125CDCFEAAE2053FEB43216613A95A71EEE6C6CB5CCBA1FD0897A824815803` |
| `OpenUxAS/mdms/PERCEIVE.xml` | `01F26999456EF1363FE039E1FAB6E40C9C7ACB82287C3E31A2B2B635F6D033A8` |
| `OpenUxAS/mdms/ROUTE.xml` | `95BE850F0FC0ED3975B1543DA768D223479210C7E6E1C493F97555DB6C245597` |
| `OpenUxAS/mdms/UXNATIVE.xml` | `1A69CC6D9767F480F20AD585BCB7F31BA42755C3590400A548DF999643A83C79` |
| `OpenUxAS/mdms/UXTASK.xml` | `227E32424E25789084B6811DAD109425812EE1EF4188D2A88FC5CE557654F707` |
| `OpenUxAS/mdms/VEHICLES.xml` | `CEFA5EDEA969A46633F2F06144BD44D602B2C3E041BD415E558A32DD8D750A85` |
| `OpenAMASE/OpenAMASE/lib/lmcplib.jar` | `F73846988D7D623D3B073C315883BCA9CE3349096406A9DD4A1986B7971728FA` |
| `OpenAMASE/OpenAMASE/config/amase/Plugins.xml` | `C843FD22ED3AF8500F33AFA98625F449A7452EA708BEBC41041E2F3AA9E09C78` |
| `OpenAMASE/OpenAMASE/config/amase_headless/Plugins.xml` | `B08450EA58949235D9EA9550978ADF836B38A7292212E16B673A205CDCE8AAF6` |
| `OpenAMASE/OpenAMASE/config/amase_headless/EntityControl.xml` | `764D8983392123C6D5DEB19837D69A826E0477F49D4AF9754981D8EC5FAC8BD9` |
| `OpenUxAS/examples/01_HelloWorld/cfg_HelloWorld.xml` | `59DA362CEC906A34ECEA66425D4AF15F025A827EAFFE908218946471D274892B` |
| `OpenUxAS/examples/01_HelloWorld/config.yaml` | `46B9A7736681520CC5BE7AA1E480A97145860DC0EEC04F47D841E511F376E674` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/cfg_WaterwaySearch.xml` | `5FD1776107C25D3463DFDA09B9508D171A29D5F67017FE754A9855F68F55F21C` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/config.yaml` | `AEAFCF24FED0758CF38693588ED5A5B088F9F737AE880CA42E20E7768466063D` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/Scenario_WaterwaySearch.xml` | `AB44112D8151D7C24AC571DD6424F0FB3E236BDD85ABB5A5FDEE85B7EA1BEB0D` |
| `OpenUxAS/infrastructure/specs/config/repositories.yaml` | `CB469DB5D59382D98DF29D29369E2A7F0C32FEE74B54E4BEBE17A4254E957798` |
| `OpenAMASE/OpenAMASE/lib/worldwind.jar` | `C519F27B564DACCFB85ED527D0D93CB32EC77734EF6C7CB222EED5F8B9D6DA88` |
| `OpenAMASE/OpenAMASE/lib/Flexdock/flexdock-1.2.3.jar` | `57BA051FC9998DE94F9C3C490C0DFBBEDE2B22E309E6B6A1383FE3C5B67F548E` |
| `OpenAMASE/OpenAMASE/lib/SwingX/swingx-all-1.6.4.jar` | `5BC8BB080FDF3EF968485AE90F7877FBCFC05B2CFE4753824ACB5A36A1EE2036` |
| `OpenAMASE/OpenAMASE/lib/GRAL/gral-core-0.10.jar` | `BB36B2C2C1F981EDFBC95062BF5126863795ECD9679B5B1776A647C1129D6D16` |
| `OpenAMASE/OpenAMASE/lib/CopyLibs/org-netbeans-modules-java-j2seproject-copylibstask.jar` | `FAE43F88FAF14CB37C913B0FB2F19DB66B597854FC01F2CD5E7C4D062F42C336` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/AirVehicleConfiguration_V400.xml` | `7496F923EF13BDC91AD1A2F843B4D777F82B3501D91F01B37EED59AE61ED4219` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/AirVehicleConfiguration_V500.xml` | `BA05D0D43683EFE066908AF787C1BD48E284CF26910FF4C204F5EA2EFF05097D` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/AirVehicleState_V400.xml` | `AD43B4006F0A136BF263713054E2B51C754D4E577EA21D4D875231E4D700AB1B` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/AirVehicleState_V500.xml` | `50A19C5DC66E18612517F29FD6608F70C5C27E56E458B5169A6C31F29269D593` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/tasks/1000_LineSearch_LINE_Waterway_Deschutes.xml` | `CEFB2CD4D150D93EABBB622A7959A090DB287560FE554629E84762A2C29D7ACC` |
| `OpenUxAS/examples/02_Example_WaterwaySearch/MessagesToSend/tasks/1001_AutomationRequest_LINE_Waterway_Deschutes.xml` | `A2530B7F160CD866D72C99A98AD2FCD388C35D7D06739DE3686B08C54D8A2D20` |
| `OpenUxAS/infrastructure/specs/patches/pugixml.patch` | `B1D08AAAAB3EC3A577A4DF0BAA3B5F7AD56D603D7B7012EC7888822046369D50` |
| `OpenUxAS/infrastructure/specs/patches/serial.patch` | `2EBA3043127DE208AD2B011957E997F709D06914F94F2D6E7C3FDF954AD34197` |
