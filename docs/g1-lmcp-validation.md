# G1-T03：统一消息代码与 Java 消息库验收

日期：2026-09-17，Asia/Shanghai。**G1-T03 已完成；G1 进行中，G1-T04 可执行但尚未启动。**

本次从七个固定 MDM 和 T02 生成器生成 Java／C++／Python 代码，编译 Java 消息库，完成文件／内存级跨语言样本及八组集成验收。没有修改生成器、模板、MDM 或 AMASE／UxAS 源码，没有替换旧 JAR，没有编译 C++、安装新工具、启动仿真或网络服务，也没有提交／推送 Git。

## 1. 输入基线与工具

根提交为 `7a3d5e6c2f8060adb40b7728fc270be387f12ac2`；保留 T01／T02 的未提交成果。LmcpGen tree 为 `5a03ccc3bead5fdbb98922a96d4e84fbfbf69c68`，上游精确 SHA 仍未知。生成前核对 T02 来源清单及其 225 项输入，全部一致。

- 生成器 SHA-256：`AE569E9C6D39741D88F2CA3712EC8C6D2B40BA3174E6D33E667FD7BF731B29BB`，T02 运行编号 `g1-t02-20260917-144647-639`。
- 工具：Temurin JDK 11.0.32.1+1、javac 11.0.32.1、Ant 1.10.18、实际 Python 3.14.7 x64。Python 来自明确指定的解释器，采用 `-I -B -X utf8` 隔离运行；未使用 WindowsApps 入口文件的存在性替代执行验证。
- 固定模型清单：[lmcp-models.json](../config/lmcp-models.json)。七个文件的 SHA-256 与 [G0 报告](g0-baseline.md)相同，身份、版本和文件集合均检查；生成时使用同一份独立快照。

| 系列 | 当前版本 | 旧 Java 库版本 | 结构类型 | 枚举 |
| --- | --- | --- | --- | --- |
| CMASI | 3 | 3 | 60 | 15 |
| IMPACT | 14 | 14 | 35 | 4 |
| PERCEIVE | 1 | 1 | 3 | 0 |
| ROUTE | 4 | 4 | 14 | 0 |
| UXNATIVE | 9 | 9 | 17 | 0 |
| UXTASK | 8 | 7 | 29 | 0 |
| VEHICLES | 1 | 1 | 6 | 0 |
| 合计 | — | — | 164 | 19 |

旧库仍为 `OpenAMASE/OpenAMASE/lib/lmcplib.jar`，SHA-256 保持 `F73846988D7D623D3B073C315883BCA9CE3349096406A9DD4A1986B7971728FA`。它只在独立比较进程中使用。

## 2. 可重复入口与发布约定

在仓库根目录使用 PowerShell；Python 变量的示例值对应本轮已核查的安装布局，其他安装布局应传入实际路径：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\generate-lmcp.ps1 -PythonExecutable $pythonExe
# 先完成一次生成，再运行包含重复生成和隔离故障的验收。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\lmcp-generation.tests.ps1 -PythonExecutable $pythonExe
```

最终上述两个入口均实际退出 0，且从其他工作目录及中文空格路径调用通过。无需永久修改 PATH 或执行策略。

| 文件 | 职责 |
| --- | --- |
| [generate-lmcp.ps1](../scripts/windows/generate-lmcp.ps1) | 按自身位置定位仓库，复用锁定工具检查，启用受控进程环境并恢复 |
| [generate.py](../scripts/lmcp/generate.py) | Python 标准库编排输入核对、快照、生成、Ant 编译、消息探针、来源清单和发布 |
| [JavaProbe.java](../tests/lmcp/JavaProbe.java) | 新旧库分别加载、公共接口与类型清单、样本编码／解码及预期拒绝 |
| [python_probe.py](../tests/lmcp/python_probe.py) | 消息包导入、工厂实例化、字段与帧比较、Python 编码及校验 |
| [samples.properties](../tests/lmcp/samples.properties) | 两种语言共享的固定样本，int64 不经过浮点转换 |
| [lmcp-generation.tests.ps1](../tests/windows/lmcp-generation.tests.ps1)、[generation_checks.py](../tests/lmcp/generation_checks.py) | 八组路径、重复、故障、回退与环境检查 |

三种语言按 Java、C++、Python 顺序生成，使用相同 JAR 和模型快照。Java 使用生成工程的 Ant `jar` 目标，source／target 保持 1.8，并设置 `-nouserlib -noinput -Dmkdist.disabled=true`。Ant 由锁定 JVM 的官方 Launcher 执行，不依赖 NetBeans 或用户 antrc 批处理；不修改生成后的构建文件。

| 用途 | 路径／属性 |
| --- | --- |
| 模型快照 | `out/build/lmcp/<run-id>/inputs/mdms/` |
| 待验生成代码 | 同一 build 目录下的 `generated/{java,cpp,py}/` |
| Java build.dir | 同一 build 目录下的 `java-build/` |
| Java dist.dir／dist.jar | 同一 build 目录下的 `artifacts/java/`／`lmcplib.jar` |
| 正式生成代码 | `out/generated/lmcp/{java,cpp,py}/` |
| 正式 Java 库 | `out/artifacts/lmcp/java/lmcplib.jar` |
| 两份清单 | 生成目录 generation-info.json、产物目录 build-info.json |
| 原始记录 | `out/runs/<run-id>/` 的 result.json、各命令 stdout／stderr、类型清单和样本 |

全部检查通过后才发布。每次独立运行且持有本项目生成锁，发布前复核输入稳定性；两份清单使用相同 runId。出现发布异常会恢复上一批生成目录和产物目录，旧备份与失败现场保留在 out。消费者必须核对 runId、输入及产物哈希，不能只根据 JAR 存在判定最新尝试成功。

build-info.json 记录本轮 19 项直接输入哈希，包括生成器和 T02 清单、七个模型、旧 Java 库、配置及生成／探针脚本；T02 清单继续追溯生成器源码。文件清单覆盖全部 1,013 个生成文件。原始记录包含命令参数、工作目录、时间、退出码与输出；绝对本机路径只保留于被忽略的 out 记录。

入口恢复 12 项进程环境值、工作目录及控制台编码；验收比较 36 项进程／用户／机器环境值和执行策略，均未改变。Python 不写入字节码缓存，不安装第三方依赖。

## 3. 实际产物与样本

首次完整构建为 `g1-t03-20260917-151758-772465`，无需任何上游兼容补丁即通过。集成验收重新执行后的正式运行编号为 **`g1-t03-20260917-152214-037296`**。

| 产物／检查 | 实测结果 |
| --- | --- |
| Java 生成文件 | 209 个，包括模型副本、运行库、消息类和构建配置 |
| C++ 生成文件 | 588 个，只检查生成完整性，没有编译 |
| Python 生成文件 | 216 个，包括消息包、模型副本及上游示例 |
| 总生成文件 | 1,013 个；另有本项目的 generation-info.json，不计入生成器文件数 |
| Java 编译 | 196 个 Java 源文件；196 个目标类均检查到字节码主版本 52 |
| Java 消息 JAR | 1,241,157 字节 |
| JAR SHA-256 | `FD6F40587AF46C380B959BD6036A2D269D87CB2D62FC50BF3AC2333E31D07E4C` |
| Python | 导入 203 个消息包／模块，创建全部 164 个结构类型并核对 Java 类型编号、系列标识及版本 |

两种语言使用同一份固定配置构造以下样本，整数精确比较，浮点值选用可精确表示的数；同时比较完整 LMCP 帧和重新编码结果：

| 样本 | 关键预期字段 | 原始 LMCP 帧长度 |
| --- | --- | --- |
| basic：CMASI AirVehicleState | ID=`400`，Time=`1234567890123`；纬度 34.25、经度 −117.5、高度 1234.5、AltitudeType=MSL、Heading=90.25、Airspeed=45.5 | 188 字节 |
| wide：CMASI AirVehicleState | ID=`9007199254740993`；关联任务 `42`、`9007199254740995`；其余与 basic 相同 | 204 字节 |
| task：UXTASK TaskActive | 版本 8，TaskID=`42`、EntityID=`400`、TimeTaskActivated=`1234567890123` | 51 字节 |

每个样本分别验证零校验和与计算校验和两种模式，共六个帧；Java→Python、Python→Java 字段及重新编码字节均一致。JSON 报告中的 int64 标识与时间使用字符串，不经过 JavaScript 数值表示。样本是固定序列化数据，不代表实际仿真运行状态。

零校验和模式使用两种库的 packMessage(false)。计算校验和时，Java 原生输出 Sentinel 帧，通过其现有 getMessageBytes 在内存中取出内部 LMCP 后，与 Python packMessage(true) 逐字节比较。旧 Java 库的四个 CMASI 帧也与新库一致，旧 Java 可解析 Python 的这四个帧。损坏校验和的样本被 Java 解码器及 Python 校验步骤拒绝。

Python getObject 本身不承担完整校验，探针先执行帧标记、长度及独立校验和检查，并调用工厂 validate；后续客户端不得省略这些步骤。

## 4. 新旧库差异与协议更正

新旧 JAR 分别在独立 JVM 中加载，同一 classpath 从不混入两个库。共比较 196 个公开目标类，183 个消息／枚举类型的名称集合一致，结构类型编号和系列标识未变。

- UXTASK 的 SeriesEnum 和 29 个结构类从版本 7 变为 8；其余系列版本一致，共 30 个类有版本元数据差异。
- RendezvousTask 移除了旧 Location、Heading、MultiLocationRendezvous 的 getter／setter 和旧完整构造函数，增加与当前字段集合对应的构造函数。这是当前 MDM 已存在的变化，本轮未改模型。
- 从 AMASE Java 源码的显式导入、通配导入和全限定名筛出 101 个静态引用类，没有发现这些类的公共接口被移除。该检查不覆盖全部动态／反射行为，也没有代替完整 AMASE 编译。
- 新 Python 工厂不识别旧 UXTASK 7 的 TaskActive；旧 Java 工厂也不识别新 UXTASK 8 样本。两项预期拒绝实测通过，因此不能宣称新旧库完全向后兼容。

详细机器可读差异在本次运行的 `library-comparison.json`、new-inventory.json 和 old-inventory.json 中。

**对早期判断的更正：**[G0 报告](g0-baseline.md)及原目录分析曾将 AMASE TCP 描述为直接读写原始 LMCP。T03 进一步核对了 [TcpServer 的调用](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/TcpServer.java)、[Java 工厂模板](../LmcpGen/src/templates/java/lmcp_factory_java)、随库 JAR 字节码和实际内存样本，确认 Java packMessage(true) 添加 Sentinel／地址／属性外层，流读取方法也处理该外层；Python 工厂输出原始 LMCP。仅根据 AMASE 调用了 LMCPFactory 就推断其 TCP 没有外层是不成立的。

G0 与此前工作日志保留为历史，当前 AGENTS、目录分析和状态页按本次证据更正。现有 UxAS TCP 桥也使用 Sentinel，不再预先认定必须新增“AMASE 原始 LMCP 专用桥”。本次没有真实 TCP 流量；外层长度、校验、增量分包、地址／属性、来源过滤和双向命令执行仍需 G1-T05／G3 验证。

## 5. 八组集成验收及过程问题

最终验收记录：`out/runs/g1-t03-validation-20260917-152213-517445/`。每组命令、工作目录、子进程退出码及构建结果保存为 JSON 和 stdout／stderr 日志，results.json 八项均为 passed。

| 场景 | 预期与实际结果 |
| --- | --- |
| 重复／其他工作目录／环境恢复 | 从任务临时目录调用正式入口，产生新批次；无效 Java／Python 环境选项被隔离，成功后进程环境、工作目录、编码恢复 |
| 中文空格项目路径 | 在 out/tmp 下的 `project 中文 space` 副本完成三语言生成、Java 编译和全部消息验证，退出 0 |
| 缺失模型 | 暂移副本 IMPACT.xml，文件集合检查失败，入口退出 1；另在同进程捕获失败后验证环境恢复；上一批所有生成文件与产物哈希不变 |
| 生成器哈希不符 | 修改副本 JAR，T02 校验失败，入口退出 1，尚未生成代码，上一批不变 |
| 损坏模型 | 副本模型改为不完整 XML，并同步副本清单哈希以实际触发 XML 解析；入口退出 1，上一批不变 |
| 消息样本失败 | 仅修改副本探针，在 Java 输出中翻转一个字节；Python 报 Invalid LMCP checksum，入口退出 1，不发布 |
| 发布中断与恢复 | 仅在副本编排脚本注入第二个目录发布失败；生成目录已经切换后触发恢复，完整上一批源码、JAR 及清单哈希均不变 |
| 正式输入与范围 | 正式产物和输入不受故障影响，HEAD／三个上游源码目录未变；上游默认 build／dist 和生成目录内 build／__pycache__ 均未产生 |

首次运行集成验收时，测试脚本将已解释为 Unicode 的中文路径再次按 ASCII 编码，发生 UnicodeEncodeError，退出 1，尚未执行测试场景。删除多余编码转换后重跑通过。首次失败目录为 `g1-t03-validation-20260917-152156-997918`，该目录不视为已完成验收；失败现象同时记录于工作日志。

生成器附带的 Python LMCPClient.py 在导入时创建 socket 并连接，因此只对顶层示例做语法检查；203 个实际消息包／模块均完成真实导入，没有启动示例网络程序。

Java 编译保留 source 8 未指定 bootstrap classpath 的警告，以及弃用 API／未检查操作提示。本任务验证的是 JDK 11 编译与运行、字节码 52，不宣称已在 JDK 8 运行。没有为清除警告调整上游源码或升级标准。

## 6. T04 交接与回退

T04 开始前检查 Git 状态，核对正式生成目录与产物目录清单的 runId、生成器／模型哈希和 JAR 哈希。通过 Ant 属性 `file.reference.lmcplib.jar` 指向 `out/artifacts/lmcp/java/lmcplib.jar`，保留旧随库 JAR 并排除 classpath 中的旧同名类。该属性接入尚未实际构建 AMASE。

T04 仍须完成完整工程编译、GUI／无界面指定场景运行；T05 接收实际状态时须处理 Java 工厂使用的外层。C++ 编译归 G2，真实 AMASE↔UxAS 双向协议与来源验证归 G3。

需要回退时只处理经解析确认位于本任务 out 子目录的文件，旧批次备份与失败日志保留；禁止拿 out/tmp 中的故障副本作为正式输入。三个上游目录与旧 JAR 未变，不需要回退业务源码。

过程记录见 [worklog.md](../worklog.md) 的 WL-20260917-006。**本轮止于 T03；T04 尚未启动，G1 整体尚未完成。**
