# G1 Java 环境与验证记录

历史记录日期：2026-09-17。截至 G1-T02 交付时的结论：**G1-T01、G1-T02 已完成；G1 进行中，G1-T03 可执行但尚未启动。** 后续 T03 的实际结果见 [统一消息库验收](g1-lmcp-validation.md)，最新进度见 [状态页](status.md)。

第 1～5 节保留 G1-T01 环境准备的历史记录，该阶段没有构建工程；第 6 节保留 G1-T02 的本地 LmcpGen 实际构建与验收。截至 T02 交付时仍未生成消息代码、构建 AMASE、启动仿真或准备 C++／Node；当时 T01、T02 均未提交或推送 Git。下列历史证据不回写为后续状态。

## 1. 输入基线与工具版本

开始时 HEAD 为 `7a3d5e6c2f8060adb40b7728fc270be387f12ac2`，工作区干净；三个上游源码目录保持 [G0 基线](g0-baseline.md)。环境仍为 Windows 11 x64、PowerShell 5.1，当前执行策略为 Restricted。

固定清单：[windows-java-toolchain.json](../config/windows-java-toolchain.json)。清单记录版本、精确 URL、压缩包、校验算法和值、安装子目录、来源、许可证文件和需要核对的关键文件。脚本不会查询最新版。

| 工具 | 固定版本 | 实际项目内安装位置 | 官方来源 |
| --- | --- | --- | --- |
| Eclipse Temurin JDK，x64／HotSpot | 11.0.32.1+1 | `.tools/jdk-11.0.32.1+1/` | [官方发布](https://github.com/adoptium/temurin11-binaries/releases/tag/jdk-11.0.32.1%2B1) |
| Apache Ant | 1.10.18 | `.tools/apache-ant-1.10.18/` | [官方二进制分发](https://ant.apache.org/bindownload.cgi) |

压缩包分别为 `OpenJDK11U-jdk_x64_windows_hotspot_11.0.32.1_1.zip`（199461714 字节）和 `apache-ant-1.10.18-bin.zip`（10413759 字节），缓存于 `.tools/downloads/`。实际下载文件与下列锁定值一致：

- JDK SHA-256：`d5008f02174c1ad21c10407cbf104815cb390ec4c263d53946e8d0507d7a77f9`。
- Ant SHA-512：`f86d7b263bc7c6903a91532943f1c8ecccc17dd999851a796617e79795908d7a666cbe999b9ecf06735cc7e830f50dca9f49b37bb5f6f02a0a3803cd22b558b0`。

许可证随原工具包保留。JDK 的相关文件位于 `legal/java.base/`，Ant 保留 `LICENSE`／`NOTICE`；本任务不修改这些文件。源地址及官方校验文件入口均保存在固定清单中。

## 2. 入口与行为

| 文件 | 职责 |
| --- | --- |
| [setup-java.ps1](../scripts/windows/setup-java.ps1) | 下载锁定工具、校验、安装或复用、执行版本检查、保存结果，并恢复临时修改的进程环境 |
| [use-java.ps1](../scripts/windows/use-java.ps1) | 验证两个工具完整性，在当前 PowerShell 进程内启用 Java／Ant |
| [java-common.ps1](../scripts/windows/java-common.ps1) | 两个入口共用的清单读取、路径约束、安装记录核对及进程环境处理；不是独立操作入口 |
| [java-toolchain.tests.ps1](../tests/windows/java-toolchain.tests.ps1) | 可重复运行的 G1-T01 验收；测试数据和编译探针仅写入 out |

两个入口按脚本自身位置定位根目录，不依赖调用时的工作目录。现有安装必须具有匹配的 `.uav-toolchain.json`，并通过关键可执行文件、库、运行时模块及许可证文件的 SHA-256 核对。安装记录用于识别当前安装和检测所列文件变化，不宣称覆盖工具目录的所有字节。

下载先写独立 `.part` 文件，校验成功才保留为缓存；解压到本次专用临时目录，核对关键文件后才放入版本目录。已有安装不匹配或缓存损坏时停止并保留现场，不自动覆盖。临时解压目录的移动、清理先校验其位置属于本项目的工具目录。

启用脚本设置当前进程的 JAVA_HOME、ANT_HOME、PATH、JAVACMD，并清空当前进程的 CLASSPATH，避免混入其他 Java 类库；重复启用不会重复添加 PATH 条目。安装脚本完成或失败后恢复上述环境变量、临时网络设置及进度设置。整个流程没有写入用户级／机器级环境变量或永久执行策略。

### 可直接复现的命令

在仓库根目录使用 PowerShell：

```powershell
# 安装或复核当前锁定版本；不构建项目。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-java.ps1

# 完整复验 G1-T01；需先准备好上述工具和下载缓存。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\java-toolchain.tests.ps1
```

需要在交互终端继续使用工具时，进入独立的 PowerShell 进程：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File .\scripts\windows\use-java.ps1
# 在上述进程内继续执行：
java -version
javac -version
ant -version
```

关闭该进程即结束本次启用。通过 `-File` 启动的子进程无法改变父终端环境；后续构建脚本应在自己的进程内调用 use-java.ps1。已有允许脚本运行的 PowerShell 进程可直接执行 `& <脚本完整路径>`。

实际版本输出：

```text
openjdk version "11.0.32.1" 2026-08-18
OpenJDK Runtime Environment Temurin-11.0.32.1+1 (build 11.0.32.1+1)
OpenJDK 64-Bit Server VM Temurin-11.0.32.1+1 (build 11.0.32.1+1, mixed mode)
javac 11.0.32.1
Apache Ant(TM) version 1.10.18 compiled on September 3 2026
```

三条版本命令的退出码均为 0。版本检查来自实际运行，不是仅读取下载文件名。

## 3. 生成物与后续 Ant 属性

根级 [.gitignore](../.gitignore)仅新增以下八项精确目录规则：

```gitignore
/.tools/
/out/
/LmcpGen/build/
/LmcpGen/dist/
/LmcpGen/nbproject/private/
/OpenAMASE/OpenAMASE/build/
/OpenAMASE/OpenAMASE/dist/
/OpenAMASE/OpenAMASE/nbproject/private/
```

没有添加全局 JAR／XML 忽略规则；随库消息库、WorldWind 和 MDM 仍属于源码基线。

后续从现有 Ant 工程构建时，使用绝对路径覆盖以下属性；它们是 T02／T04 的执行约定，**本轮未实际构建两个工程，也未验证其完整依赖**：

| 组件 | build.dir | dist.dir | dist.jar |
| --- | --- | --- | --- |
| LmcpGen | `<根>/out/build/lmcpgen` | `<根>/out/artifacts/lmcpgen` | `<根>/out/artifacts/lmcpgen/LmcpGen.jar` |
| AMASE | `<根>/out/build/amase` | `<根>/out/artifacts/amase` | `<根>/out/artifacts/amase/OpenAMASE.jar` |

两者现有 project.properties 的 classes、generated、javadoc 等目录引用 build.dir 或 dist.dir；上游文件未修改。若后续实际构建仍向源目录写入其他文件，应记录具体路径并作最小修复，不能只复制最终 JAR 就认定输出隔离通过。AMASE 的统一 Java 消息库接入仍由 T03／T04 完成。

消息生成继续使用 `out/generated/lmcp/{java,cpp,py}/`。本轮只创建工具、检查记录和临时探针；项目级 out/build、out/artifacts、out/generated 以及两个上游工程 build／dist 均未创建。

## 4. 验收证据

首次安装于 2026-09-17T11:32:08+08:00 开始，11:32:46 完成；命令退出码为 0。八组验收于 11:35～11:36 完成，测试入口退出码为 0。

| 场景 | 验证方法与实际结果 |
| --- | --- |
| 重复安装、不同工作目录、环境恢复 | 从临时目录调用安装入口；两个工具均标为 reused，当前进程的五项环境变量恢复原值 |
| 环境启用与 Java 8／11 探针 | 连续启用两次 PATH 不重复；Ant 编译两个目标并执行，输出两次 PROBE_OK；class 主版本分别为 52／55，记录的 java.home 等于锁定 JDK |
| 缺失工具 | 隔离项目没有安装记录，启用失败；正式进程的工具环境未被部分修改 |
| 损坏缓存 | 隔离项目使用故意损坏的 JDK 压缩包，安装退出 1；未安装该工具 |
| 下载失败 | 隔离清单将 URL 指向本机不可用端口，退出 1；结果记录为 failed，未留下下载临时文件 |
| 中文与空格路径 | 在 `out/tmp/<本次编号>/project 中文 space/` 复制入口和缓存，实际安装并执行 Ant 探针；安装与编译均退出 0 |
| 安装文件或版本记录被修改 | 仅修改隔离副本的 ant.bat 和安装记录版本；启用／安装分别退出 1，正式工具未受影响 |
| 正式环境与源码 | 正式工具核对通过；用户级／机器级环境保持不变；三个上游源码目录无改动 |

故障场景的退出码 1 是预期结果，不计为验收失败。探针仅使用一个独立 Java 类和最小 Ant 配置，不包含 LmcpGen、AMASE、MDM 或仿真代码。

原始记录位置（本机生成、不提交 Git）：

- 首次安装：`out/runs/g1-t01-setup-20260917-113208-149/`，含 setup.log、result.json。
- 重复安装：`out/runs/g1-t01-setup-20260917-113530-491/`。
- 八组验收：`out/runs/g1-t01-validation-20260917-113530-456/`，含 validation.log、results.json 和各子场景日志。
- 初始环境快照：`out/runs/g1-t01-session/`。
- 探针及故障副本：`out/tmp/g1-t01-validation-20260917-113530-456/`；其中部分工具被故意损坏，只作为故障验证现场，不应用于后续构建。

11:36 的独立范围复核还确认：15 项进程／用户／机器环境值、5 项执行策略保持不变；8 个应忽略路径命中规则，5 个源码／脚本代表路径不被忽略；项目构建输出目录不存在。

11:45:36 的交付复核通过：12 个文件严格 UTF-8／PowerShell 语法检查、88 个本地链接及锚点、22 个 Markdown 表格与围栏结构正常；两个压缩包哈希和八组验收结果一致。五份未涉及的历史文档与既有日志内容保持不变，三个上游源码目录和 Git HEAD 未变。汇总保存在 `out/runs/g1-t01-session/final-validation.json`。

## 5. 交接与回退

**G1-T01 验收通过，下一任务 G1-T02：构建本地 LmcpGen。** Java 8／11 探针通过不代表生成器、AMASE 或随库 Java 依赖兼容；这些验证分别归 T02～T04。Python 生成消息兼容性和真实状态接收仍归 T03／T05。

Java 环境缺口及根级生成物管理缺口已处理。C++／Node、Java 消息库一致性、协议封装、旧启动路径和地形问题维持原任务归属。

回退时关闭启用工具的 PowerShell 进程；如需清理工具或探针，先核对解析后的绝对路径属于本任务的 .tools／out 子目录，再只处理这些目录。源码与 Git 历史不需回退；本轮新增脚本、清单、忽略规则及文档尚未提交。历史 G0 报告和既有日志保持原样，当前过程见 [worklog.md](../worklog.md)。

## 6. G1-T02：本地 LmcpGen 构建与验收

2026-09-17（Asia/Shanghai）实际执行通过。使用已有 T01 工具，从当前源码构建新 JAR；没有重新下载工具，没有改动上游源码、构建文件、模板或 MDM。T01 的未提交修改完整保留。

### 输入与正式产物

| 项目 | 实测记录 |
| --- | --- |
| 根提交 | `7a3d5e6c2f8060adb40b7728fc270be387f12ac2` |
| 本地 LmcpGen tree | `5a03ccc3bead5fdbb98922a96d4e84fbfbf69c68`，与 G0 一致；上游精确 SHA 仍未知 |
| 实际输入清单 | 220 个 LmcpGen 文件，以及 CMASI、工具清单和三个构建／环境脚本，共 225 项 SHA-256 |
| CMASI SHA-256 | `EBF4D93CD57F798CF9D4CCC5464C4BED23FD113277F7956543885897C29BF360` |
| 工具 | Temurin 11.0.32.1+1、javac 11.0.32.1、Ant 1.10.18；实际版本命令均退出 0 |
| 正式运行编号 | `g1-t02-20260917-144647-639`，重复构建后的最终产物 |
| 产物 | `out/artifacts/lmcpgen/LmcpGen.jar`，1,763,536 字节 |
| JAR SHA-256 | `AE569E9C6D39741D88F2CA3712EC8C6D2B40BA3174E6D33E667FD7BF731B29BB` |
| 清单主类 | `avtas.lmcp.lmcpgen.LmcpGenGUI`；带参数转到 CLI，不创建 GUI |
| 字节码与资源 | LmcpGen、LmcpGenGUI、MDMReader 主版本均为 52；184 个内置 DTD／模板文件与源码 SHA-256 一致 |

同目录 `build-info.json` 保存源码／脚本／工具清单哈希、Git 标识、实际工具位置和版本、完整参数数组、工作目录、起止时间、退出码、输出、JAR 检查与哈希。哈希以实际构建输入为准，根提交不会被误认为包含尚未提交的脚本。隔离副本没有自己的 Git 元数据，清单明确使用文件哈希，不冒认父仓库的提交。

### 入口、输出与失败处理

在仓库根目录执行；两个入口均按自身位置定位项目，也可从其他工作目录用绝对路径调用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-lmcpgen.ps1
# 先完成上面的构建，再执行包含重复构建及隔离故障的验收。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\lmcpgen-build.tests.ps1
```

构建入口为 [build-lmcpgen.ps1](../scripts/windows/build-lmcpgen.ps1)，验收入口为 [lmcpgen-build.tests.ps1](../tests/windows/lmcpgen-build.tests.ps1)。两次命令实际退出码均为 0。

脚本复用 use-java.ps1 的工具核验与进程环境设置，使用锁定的 java.exe 调用 Ant 自带 `org.apache.tools.ant.launch.Launcher`，避免执行用户的 antrc 批处理。实质构建参数为 `-nouserlib -noinput -f <LmcpGen/build.xml> -Dmkdist.disabled=true -Djavac.source=1.8 -Djavac.target=1.8 jar`，输出映射如下：

| 属性／用途 | 实际约定 |
| --- | --- |
| build.dir | `out/build/lmcpgen/<run-id>/` |
| dist.dir | 本次 build.dir 下的 `candidate/` |
| dist.jar | 本次 candidate 下的 `LmcpGen.jar` |
| 正式交付 | `out/artifacts/lmcpgen/LmcpGen.jar` 和 `build-info.json` |
| 原始证据 | `out/runs/<run-id>/` 的 build.log、各命令日志与 result.json |

每次从新目录编译，候选 JAR 通过内容、CLI、输入稳定性检查后才发布。发布前核对复制后的哈希；已有正式目录移到本次构建目录的 previous-artifacts，正常异常处理会尝试恢复。构建文件锁避免同项目并行发布；旧备份和失败现场均保留，不自动递归清理。发布目录含旧产物不代表最新尝试成功，须查看对应 result.json。

脚本在本进程临时统一 UTF-8 编码及英文 JVM 诊断，清除影响 Java／Ant 的额外选项，结束时恢复十项环境变量、工作目录和控制台输出编码；不改用户／机器环境或持久执行策略。运行编号和 ZIP 时间戳会变化，重复构建不要求 JAR 字节完全一致。

### 实际验收结果

首次正式构建为 `g1-t02-20260917-143411-694`，编译 21 个 Java 文件，复制 211 个资源文件，Ant、帮助及 CMASI 检查均退出 0。随后修正日志编码，14:37 的六组验收通过；收尾增加运行目录重名保护后于 14:47 再次完成六组验收，最终运行编号见上表。

六组验收记录位于 `out/runs/g1-t02-validation-20260917-144647-347/`，results.json 六项均为 passed，各用例 JSON 保存完整命令、工作目录、原始退出码及构建结果：

| 场景 | 预期与实测 |
| --- | --- |
| 重复构建／其他工作目录／环境恢复 | 从任务临时目录调用真实入口；使用新构建目录，退出 0；注入无效 Java／Ant 环境选项后仍成功；强制运行目录重名被拒绝，原 result.json 哈希不变；成功及重名失败后十项进程环境值、工作目录及编码均恢复 |
| 中文与空格项目路径 | 在 `out/tmp/<验收编号>/project 中文 space/` 复制源码、入口和正式工具，实际构建及 CLI 均退出 0，资源完整 |
| 缺失 CMASI | 在副本中暂移模型文件；入口退出 1，停在 preflight，尚未调用 Java；已有 JAR 与来源清单哈希不变 |
| 损坏 CMASI | 副本模型改为未闭合 XML；原 CLI 退出 0 并输出 Error／Fatal Error，入口据诊断退出 1；已有产物不变 |
| 编译错误 | 仅在副本增加语法错误文件；Ant 与入口均退出 1，停在 ant-build，不运行 CLI，不替换产物 |
| 正式工具／范围／持久环境 | 工具关键文件核验通过，正式 JAR 不受故障影响；上游跟踪文件、HEAD、20 项用户／机器环境值和执行策略不变；输出忽略生效 |

故障均为隔离测试的预期失败。正式项目没有 LmcpGen 默认 build／dist、AMASE build／dist 或 out/generated；所有模型与源码仍保持原状。副本保留作为测试现场，T03 只使用正式产物及其清单。

### 警告、限制与交接

- javac 留下一个 `bootstrap class path not set in conjunction with -source 8` 警告，以及弃用 API／未检查操作提示。本任务按原工程使用 source／target 1.8，没有升级标准或调整业务代码。字节码 52 与 JDK 11 上运行通过，不等于已在 JDK 8 运行或验证所有 Java 8 API 兼容性。
- 首次输出受 Windows 默认字符集与 UTF-8 控制台差异影响出现乱码；统一进程编码和诊断语言后，重复构建日志可读，未修改原警告对应的源码。
- 缺失 manifest.mf 不构成故障：上游 Ant 自动生成 Main-Class；未额外添加清单文件。
- 原 `-checkMDM` 会吞掉部分错误的失败退出码。本入口先验证文件存在，再要求退出 0 且没有诊断输出；原生成器行为保留。T03 必须继续检查实际生成结果，不能仅凭退出码通过。
- 收尾审查发现运行目录重名时 finally 可能改写已有 result.json；仅允许向本次成功创建的目录写结果，强制重名的隔离验证确认旧记录不变。
- CMASI 读取成功尚未证明七个模型的关联、跨语言生成与消息往返正确；这些属于 T03。AMASE 与旧随库消息库兼容性仍属 T03／T04。

**G1-T02 验收通过。下一任务 G1-T03 可执行但尚未启动，G1 整体仍在进行中。** 尚未生成消息代码、构建 AMASE、安装 C++／Node、启动仿真或执行 Git 提交／推送。工作过程见 [worklog.md](../worklog.md) 的 WL-20260917-005。
