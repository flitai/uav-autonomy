# 项目实施状态

更新日期：2026-09-17。依据：[总体实施计划](../04.项目总体实施计划与阶段验收.md)、[G0 报告](g0-baseline.md)、[Java 环境验收](g1-java-validation.md)、[T03 消息库验收](g1-lmcp-validation.md)、[T04 AMASE 验收](g1-amase-validation.md)、[T05 TCP 验收](g1-tcp-validation.md)、[任务清单](backlog.md)。过程记录见根级 [worklog.md](../worklog.md)。

## 当前关卡

**G0、G1 已完成，G1-T01～T05 均已完成；G2 待细化，尚未启动。**

| 项目 | 当前记录 |
| --- | --- |
| 最近通过的任务 | G1-T05：两种模式真实 TCP 接收、十四组自动验收、GUI 人工确认、同版本受控复验及正常退出；G1 阶段验收通过 |
| 源码基线 | T05 起点为 `164927d`；本轮新增独立接收与验收脚本，保持上游源码、T04 实现及 T03 消息产物不变 |
| 已归档历史 | G1-T01～T03 实现为 `304def9`，G1-T04 为 `f2f73ab`，G1-T05 为 `d77dd78`，均已推送到 origin/main；操作收尾记录另随文档提交归档 |
| 本轮变更 | T05 增量解析器、只接收客户端、自动验收及人工收尾已完成；实现已提交推送并核对远程一致。实施过程见 WL-20260917-009，提交记录见 WL-20260917-010 |
| 已验证工具 | 项目内 Temurin JDK 11.0.32.1+1、Ant 1.10.18；实际 Python 3.14.7 x64 已通过生成消息包验证，Git 2.55.0.windows.3 |
| 已验证能力 | GUI／无界面真实 TCP 实体与会话状态；两层校验、四种分包回放、同次事件对应、中文空格路径、重复运行及故障拒绝；无界面完整场景退出 |
| 尚未验证能力 | C++ 编译、UxAS 双向网络、完整重连、重置分段验收、原系统闭环、Cesium；Python 其他项目依赖 |
| 下一动作 | 细化 G2：Windows 原生 UxAS 的工具链、依赖及最小构建任务；尚未启动 |
| 当前边界 | 本轮客户端、GUI 与无界面实例均已退出，六个端口释放；未替换旧库、改动 T04 实现、接入 UxAS／Cesium或安装新工具 |

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
| C++／Node 与旧依赖补丁（R02／R10） | 未安装或验证 | 分阶段准备工具并做最小构建 | G2／G5 |

上游精确 SHA 未知（R01）、Anod 来源绑定（R05）继续按 [G0 风险表](g0-baseline.md#6-风险归属与下一次验证)执行。G0 保留为历史快照，本页反映当前进度。

## 当前使用约定

- Java 工具通过固定清单与项目内脚本使用，安装目录和下载缓存位于被忽略的 `.tools/`；不修改持久环境变量或执行策略。
- Java／C++／Python 消息已由同一组 `OpenUxAS/mdms/` 快照生成，模型身份与哈希锁定在 `config/lmcp-models.json`，输出为 `out/generated/lmcp/{java,cpp,py}/`；C++ 尚未编译。
- LmcpGen 通过 `scripts/windows/build-lmcpgen.ps1` 构建；正式产物为 `out/artifacts/lmcpgen/LmcpGen.jar`，同目录 build-info.json 记录输入、工具与验收。每次中间物放在 `out/build/lmcpgen/<run-id>/`，失败不替换已有合格产物；其他组件沿用 build.dir／dist.dir／dist.jar 覆盖约定。
- 消息通过 `scripts/windows/generate-lmcp.ps1 -PythonExecutable <实际解释器路径>` 生成与验证；正式 Java 库为 `out/artifacts/lmcp/java/lmcplib.jar`。使用前核对生成目录 generation-info.json 与产物目录 build-info.json 的运行编号、模型及文件哈希。旧随库 JAR 保留，不允许同一 classpath 混入新旧版本。
- AMASE 通过 build-amase.ps1 构建候选，完成验收后正式发布到 `out/artifacts/amase/`；run-amase.ps1 默认使用正式目录，配置与资源隔离到本次运行目录。标准命令和显式端口参数见 T04 报告。
- 实际 TCP 接收通过 receive-amase.ps1 指定本次 AmaseRunId；amase-tcp.tests.ps1 自动运行两种模式、分包／故障及路径验收，Finalize 需要本轮真实 GUI 人工确认。客户端仅接收不发送；来源、数据与统计保存在独立 out/runs 目录，标准命令见 T05 报告。
- 运行记录与临时探针分别位于 `out/runs/`、`out/tmp/`，不进入 Git。隔离故障副本不能充当正式工具。
- 各任务独立验收并追加根级工作日志；本次已核对 T01～T05 全部证据后登记 G1 完成，不据此宣布原系统闭环通过。

## 下一次工作的起点

下一关卡为 [G2 Windows 原生 UxAS](backlog.md#4-后续关卡占位)，先细化工具链、依赖版本与 Windows 最小构建任务。T05 最终自动批次为 `g1-t05-automatic-20260917-222209-133086`，收尾批次为 `g1-t05-finalize-20260917-222451-856588`，均已通过；GUI 已正常退出。

后续并行运行时，GUI 使用 5555／9400／9500，无界面可使用 5556 和实体端口偏移 10000，不能只修改主端口。真实接收已与内部事件交叉核验；T05 不包含发送指令或 UxAS 联调。本轮未安装 C++ 工具，也未自动进入 G2。
