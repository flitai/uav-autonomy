# 项目实施状态

更新日期：2026-09-17。依据：[总体实施计划](../04.项目总体实施计划与阶段验收.md)、[G0 报告](g0-baseline.md)、[Java 环境验收](g1-java-validation.md)、[T03 消息库验收](g1-lmcp-validation.md)、[任务清单](backlog.md)。过程记录见根级 [worklog.md](../worklog.md)。

## 当前关卡

**G0 已完成；G1 进行中，G1-T01～T03 已完成，G1-T04 可执行但尚未启动。**

| 项目 | 当前记录 |
| --- | --- |
| 最近通过的任务 | G1-T03：统一消息生成、Java 库、Java／Python 双向样本及八组集成验收 |
| 源码基线 | 三个上游源码目录保持 G0 的根提交／tree 内容；本轮起点为 `7a3d5e6` |
| 已归档历史 | 前期文档与工作日志制度已归档；G1-T01～T03 实现归档为 `304def9`，已推送到 origin/main；操作收尾记录另随文档提交归档 |
| 本轮变更 | T01～T03 的工具准备、构建／生成入口、探针和文档已提交；工具缓存、生成代码、构建产物与原始日志仍保留在本机受忽略目录；过程见 worklog 的 WL-20260917-007 |
| 已验证工具 | 项目内 Temurin JDK 11.0.32.1+1、Ant 1.10.18；实际 Python 3.14.7 x64 已通过生成消息包验证，Git 2.55.0.windows.3 |
| 已验证能力 | 七个模型生成三种语言共 1,013 个文件，Java 编译 196 个源文件，Python 导入 203 个消息模块；三个样本的六个帧双向往返一致，新旧库比较及故障恢复通过 |
| 尚未验证能力 | C++ 编译、AMASE 构建／仿真、真实网络通信、原系统闭环、Cesium；Python 其他项目依赖 |
| 下一任务 | G1-T04：显式接入统一 Java 消息库，构建并运行 AMASE |
| 当前边界 | 停在 G1-T03 交付；未替换随库 JAR，未构建 AMASE、安装 C++／Node 或启动仿真／TCP 服务 |

## 已处理项与剩余缺口

| 项目 | 当前结论 | 下一次最小验证 | 归属 |
| --- | --- | --- | --- |
| Java／javac／Ant（R02 的 Java 部分） | 已成功构建 LmcpGen 与统一消息库，固定版本在项目 .tools 下 | T04 复用受控进程环境 | G1-T04 |
| 生成物管理（R07） | 生成器与消息库输出隔离、失败保留、发布中断恢复均通过 | 验证 AMASE 输出隔离与新库 classpath | G1-T04 |
| Java 源码与依赖兼容性 | 生成器与消息库在 JDK 11 通过；source／target 1.8 警告保留；AMASE 未编译 | 实际构建 AMASE；不将字节码 52 等同于已验证 JDK 8 运行 | G1-T04 |
| 生成器 CLI 诊断 | T02 检查诊断，T03 还检查输出文件、编译、类型清单与双向样本 | 后续保持输入／输出及版本校验 | G1-T04／T05 |
| 消息库一致性及 Python（R03／R09） | 统一代码和固定样本通过；UXTASK 7→8，RendezvousTask 有旧接口移除；101 个 AMASE 静态引用类未发现公共接口缺失 | 显式接入新库并实际构建；动态使用与运行仍待验证 | G1-T04 |
| AMASE 路径与地形（R06／R08） | 旧脚本和随库 DTED 缺口仍待运行核查 | 显式工作目录启动指定场景，记录地形来源／缺省行为 | G1-T04 |
| AMASE 与 UxAS 封装（R04） | 已更正早期判断：当前新旧 Java 库均含 Sentinel／属性外层；Python 输出原始 LMCP；文件／内存样本通过，网络未验证 | G1-T05 取得真实样本，G3 核查分包、属性、来源、过滤及双向闭环 | G1-T05／G3 |
| C++／Node 与旧依赖补丁（R02／R10） | 未安装或验证 | 分阶段准备工具并做最小构建 | G2／G5 |

上游精确 SHA 未知（R01）、Anod 来源绑定（R05）继续按 [G0 风险表](g0-baseline.md#6-风险归属与下一次验证)执行。G0 保留为历史快照，本页反映当前进度。

## 当前使用约定

- Java 工具通过固定清单与项目内脚本使用，安装目录和下载缓存位于被忽略的 `.tools/`；不修改持久环境变量或执行策略。
- Java／C++／Python 消息已由同一组 `OpenUxAS/mdms/` 快照生成，模型身份与哈希锁定在 `config/lmcp-models.json`，输出为 `out/generated/lmcp/{java,cpp,py}/`；C++ 尚未编译。
- LmcpGen 通过 `scripts/windows/build-lmcpgen.ps1` 构建；正式产物为 `out/artifacts/lmcpgen/LmcpGen.jar`，同目录 build-info.json 记录输入、工具与验收。每次中间物放在 `out/build/lmcpgen/<run-id>/`，失败不替换已有合格产物；其他组件沿用 build.dir／dist.dir／dist.jar 覆盖约定。
- 消息通过 `scripts/windows/generate-lmcp.ps1 -PythonExecutable <实际解释器路径>` 生成与验证；正式 Java 库为 `out/artifacts/lmcp/java/lmcplib.jar`。使用前核对生成目录 generation-info.json 与产物目录 build-info.json 的运行编号、模型及文件哈希。旧随库 JAR 保留，不允许同一 classpath 混入新旧版本。
- 运行记录与临时探针分别位于 `out/runs/`、`out/tmp/`，不进入 Git。隔离故障副本不能充当正式工具。
- 各任务独立验收并追加根级工作日志；G1-T01～T03 完成不等于 G1 整体通过。

## 下一次工作的起点

先读取 [G1-T04 任务卡](backlog.md#g1-t04接入统一-java-消息库验证-amase)，检查最新 Git 状态，再核对 [T03 报告](g1-lmcp-validation.md)、正式 JAR 与两份来源清单。当前工具已验证，通常无需再次下载。

T04 用 Ant 的 `file.reference.lmcplib.jar` 属性指向新库，检查实际 classpath 排除旧库，再构建并验证指定场景的 GUI／无界面模式。不能以 T03 的静态引用检查代替工程构建；Python 原始帧也不能直接作为 AMASE TCP 输入。本轮尚未启动 T04。任务结束先验证，随后追加 worklog、更新本页与 backlog，再交付；遇阻或中断同样记录过程和恢复条件。
