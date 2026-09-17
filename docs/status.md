# 项目实施状态

更新日期：2026-09-17。依据：[总体实施计划](../04.项目总体实施计划与阶段验收.md)、[G0 报告](g0-baseline.md)、[Java 环境验收](g1-java-validation.md)、[T03 消息库验收](g1-lmcp-validation.md)、[T04 AMASE 验收](g1-amase-validation.md)、[任务清单](backlog.md)。过程记录见根级 [worklog.md](../worklog.md)。

## 当前关卡

**G0 已完成；G1 进行中，G1-T01～T04 已完成，G1-T05 可执行但尚未启动。**

| 项目 | 当前记录 |
| --- | --- |
| 最近通过的任务 | G1-T04：AMASE 构建、GUI／严格无界面运行、十一组自动验收、人工确认、正常退出与正式发布 |
| 源码基线 | T04 起点为 `45debc2`；AMASE Application／UserExceptions 增加最小无界面适配，其余上游源码及消息模型保持原内容 |
| 已归档历史 | 前期文档与工作日志制度已归档；G1-T01～T03 实现归档为 `304def9`，已推送到 origin/main；操作收尾记录另随文档提交归档 |
| 本轮变更 | T04 构建／启动／验收入口、独立运行探针、最小无界面适配及报告已完成；正式产物已发布，提交推送收尾中，过程见 WL-20260917-008 |
| 已验证工具 | 项目内 Temurin JDK 11.0.32.1+1、Ant 1.10.18；实际 Python 3.14.7 x64 已通过生成消息包验证，Git 2.55.0.windows.3 |
| 已验证能力 | 保留 T03 的统一消息及跨语言验收；AMASE 737 个类、57 个资源，GUI 内部状态变化和完整 785 秒无界面仿真通过，人工确认后正常退出；正式产物已发布 |
| 尚未验证能力 | C++ 编译、实际 TCP 消息解析、原系统闭环、Cesium；Python 其他项目依赖 |
| 下一任务 | G1-T05：接收并解析实际 TCP 状态，完成 G1 验收；尚未启动 |
| 当前边界 | T04 的 AMASE 进程已正常退出；未替换旧消息库、接入 UxAS／Cesium、启动外部消息客户端或安装新工具 |

## 已处理项与剩余缺口

| 项目 | 当前结论 | 下一次最小验证 | 归属 |
| --- | --- | --- | --- |
| Java／javac／Ant（R02 的 Java 部分） | 已构建 LmcpGen、统一消息库和 AMASE，固定版本在项目 .tools 下 | 后续复用受控环境，无需重新下载 | G1-T05 |
| 生成物管理（R07） | AMASE 构建、运行和配置副本均隔离；已成套发布，退出和端口释放通过 | 启动前继续核对来源清单与端口 | G1-T05 |
| Java 源码与依赖兼容性 | AMASE 保持 source／target 11；统一消息库保留 Java 8 字节码，指定场景通过 | 新场景按任务验证；不宣称已在 JDK 8 运行 | 后续任务 |
| 生成器 CLI 诊断 | T02 检查诊断，T03 还检查输出文件、编译、类型清单与双向样本 | 后续保持输入／输出及版本校验 | G1-T04／T05 |
| 消息库一致性及 Python（R03／R09） | 完整 AMASE 编译和指定场景使用新库通过；UXTASK 7→8 的兼容差异仍成立 | 验证实际 TCP 样本，其他场景的动态使用按任务检查 | G1-T05 |
| AMASE 路径与地形（R06／R08） | 不同工作目录、中文空格路径通过；无 DTED 使用现有零高程缺省值 | 真实地形和高度验证仍需另备数据 | 后续地形验证 |
| AMASE 与 UxAS 封装（R04） | 已更正早期判断：当前新旧 Java 库均含 Sentinel／属性外层；Python 输出原始 LMCP；文件／内存样本通过，网络未验证 | G1-T05 取得真实样本，G3 核查分包、属性、来源、过滤及双向闭环 | G1-T05／G3 |
| C++／Node 与旧依赖补丁（R02／R10） | 未安装或验证 | 分阶段准备工具并做最小构建 | G2／G5 |

上游精确 SHA 未知（R01）、Anod 来源绑定（R05）继续按 [G0 风险表](g0-baseline.md#6-风险归属与下一次验证)执行。G0 保留为历史快照，本页反映当前进度。

## 当前使用约定

- Java 工具通过固定清单与项目内脚本使用，安装目录和下载缓存位于被忽略的 `.tools/`；不修改持久环境变量或执行策略。
- Java／C++／Python 消息已由同一组 `OpenUxAS/mdms/` 快照生成，模型身份与哈希锁定在 `config/lmcp-models.json`，输出为 `out/generated/lmcp/{java,cpp,py}/`；C++ 尚未编译。
- LmcpGen 通过 `scripts/windows/build-lmcpgen.ps1` 构建；正式产物为 `out/artifacts/lmcpgen/LmcpGen.jar`，同目录 build-info.json 记录输入、工具与验收。每次中间物放在 `out/build/lmcpgen/<run-id>/`，失败不替换已有合格产物；其他组件沿用 build.dir／dist.dir／dist.jar 覆盖约定。
- 消息通过 `scripts/windows/generate-lmcp.ps1 -PythonExecutable <实际解释器路径>` 生成与验证；正式 Java 库为 `out/artifacts/lmcp/java/lmcplib.jar`。使用前核对生成目录 generation-info.json 与产物目录 build-info.json 的运行编号、模型及文件哈希。旧随库 JAR 保留，不允许同一 classpath 混入新旧版本。
- AMASE 通过 build-amase.ps1 构建候选，完成验收后正式发布到 `out/artifacts/amase/`；run-amase.ps1 默认使用正式目录，配置与资源隔离到本次运行目录。标准命令和显式端口参数见 T04 报告。
- 运行记录与临时探针分别位于 `out/runs/`、`out/tmp/`，不进入 Git。隔离故障副本不能充当正式工具。
- 各任务独立验收并追加根级工作日志；G1-T01～T04 完成不等于 G1 整体通过。

## 下一次工作的起点

下一任务为 [G1-T05 任务卡](backlog.md#g1-t05接收并解析实际状态完成-g1-验收)。先核对 [T04 报告](g1-amase-validation.md)、正式 AMASE／LMCP 来源清单和当前端口，再准备最小 TCP 客户端。当前工具已验证，通常无需再次下载。

本次 GUI 与无界面进程都已退出。下次若并行运行，GUI 使用 5555／9400／9500，无界面可显式使用 5556 和实体端口偏移 10000，不能只修改主端口。内部事件证据不替代实际 TCP 解码；T05 尚未启动。
