# G1-T04：AMASE 构建与运行验收

日期：2026-09-17，Asia/Shanghai。**G1-T04 已完成：十一组自动验收通过，GUI 确认后正常退出，正式产物已发布。G1 进行中，G1-T05 可执行但尚未启动。**

以上为 T04 完成时的历史快照。后续 T05 的真实 TCP 验收及最新进度见 [T05 报告](g1-tcp-validation.md)和 [当前状态](status.md)；本报告保留 T04 原始证据。

## 1. 输入、边界与构建

实施起点为 `45debc2e192f2f839b5ae10149d4d7e1812b2e86`。使用 T03 批次 `g1-t03-20260917-152214-037296` 的统一消息库，JAR SHA-256 为 `FD6F40587AF46C380B959BD6036A2D269D87CB2D62FC50BF3AC2333E31D07E4C`；七模型、生成代码与消息库未修改。

工具沿用 Temurin JDK 11.0.32.1+1、Ant 1.10.18；脚本编排使用已验证的 Python 3.14.7 x64，仅标准库。AMASE 保留工程声明的 source／target 11，统一消息库仍为 Java 8 字节码。

Ant 使用现有 jar 目标，覆盖 build.dir、dist.dir、dist.jar、file.reference.lmcplib.jar 和明确的 javac.classpath；使用 -nouserlib、-noinput，关闭 CopyLibs 分发与原生打包。运行依赖仅为新消息库、Flexdock 1.2.3、SwingX 1.6.4、GRAL 0.10、WorldWind 随库 JAR，加独立验收插件；不使用 lib 通配符。

构建检查得到 737 个 AMASE 类，均为字节码 55；57 个非 Java／form 资源与源码一致，主类为 avtas.app.Application，没有打入 LMCP 重复类。候选来源清单同时记录实际输入哈希、依赖、命令与工具版本；每次运行重新核对当前输入和 T03 产物。

## 2. 标准入口与输出

从仓库根目录运行；脚本通过自身位置定位项目，从其他工作目录调用同样支持。Python 参数须指向实际可运行解释器，省略时从当前 PATH 查找并验证。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-amase.ps1 -PythonExecutable $pythonExe
# 用构建输出的 BUILD_RUN_ID 替换下列占位符。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-amase.ps1 -Mode Gui -BuildRunId '<BUILD_RUN_ID>' -ValidateRun -PythonExecutable $pythonExe
# GUI 保留期间，无界面副本显式使用另一组主端口／实体端口。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-amase.ps1 -Mode Headless -Port 5556 -EntityPortOffset 10000 -SimRate 20 -BuildRunId '<BUILD_RUN_ID>' -ValidateRun -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\amase.tests.ps1 -BuildRunId '<BUILD_RUN_ID>' -GuiRunId '<GUI_RUN_ID>' -PythonExecutable $pythonExe
```

`-Scenario` 可指定绝对场景路径，默认使用原 WaterwaySearch；`-ValidateRun` 验收固定场景。未开启该开关的 GUI 保留原有人工启动方式；默认倍率 GUI 为 1，无界面为 20。`-EntityPortOffset` 默认 0，只在运行配置副本中对本场景活动实体的端口加偏移；端口冲突、重复或超出范围均报错，不静默改选。

| 用途 | 位置／行为 |
| --- | --- |
| 候选构建 | `out/build/amase/<build-run-id>/candidate/`，尚未通过整个任务时不会覆盖正式产物 |
| 正式产物 | 已发布 `out/artifacts/amase/OpenAMASE.jar`、build-info.json 及独立 validation/amase-probe.jar |
| 运行证据 | `out/runs/<run-id>/`，保存 result.json、stdout／stderr、真实事件 events.jsonl，GUI 另存窗口截图 |
| 有效运行环境 | 本次运行目录下 runtime，包含配置／场景／data 副本、tmp 和 home；原场景哈希不变 |
| 隔离故障与中文路径 | `out/tmp/<validation-run-id>/project 中文 space/`；禁止用于后续正式任务 |

正式发布后，可省略 BuildRunId 使用正式产物。人工确认后通过验收入口的 `-Action Finalize`，提供 BuildRunId、GuiRunId、ValidationRunId 和实际 ManualConfirmation；入口先核对自动结果和批次，再请求 GUI 正常退出、核对端口释放，最后成套发布。未收到人工确认不得调用该步骤。

## 3. 运行证据与兼容修复

独立 RuntimeProbe 通过 AMASE 内部事件系统监听两实体及 SessionStatus，保存源时间、经纬高、墙钟、插件清单和实际类加载来源。实体 ID／时间以十进制字符串保存；仿真毫秒不解释为 UTC。GUI 用现有 SimTimer 接口推进至少 20 秒后暂停，保留窗口供人工验证；无界面由原 ConstructiveControl 自动运行原场景全部 785 秒。

本轮仅对上游两个文件作必要修复：

- [Application.java](../OpenAMASE/OpenAMASE/src/Core/avtas/app/Application.java)：无界面时不创建闪屏；未捕获异常输出堆栈，便于定位失败。
- [UserExceptions.java](../OpenAMASE/OpenAMASE/src/Core/avtas/app/UserExceptions.java)：无界面时使用日志记录错误／警告；GUI 仍使用原对话框。

严格无界面使用 `java.awt.headless=true`；修复前实际触发 HeadlessException，修复后初次完整运行约 39.26 秒，正常退出。无需修改文件选择器、场景、生成器或消息语义。

除全局 TCP 外，EntityNetworkModule 对实体 400／500 还监听 9400／9500。GUI 使用 5555、9400、9500；并行无界面验收明确使用 5556、19400、19500。检查端口实际归属本次 PID，正常退出后检查全部释放；本任务不连接这些 TCP 服务收取消息。

未提供 DTED，TerrainService／DTEDCache 在缺失瓦片时返回零高程；观测插件在场景位置取得 0。本地世界底图存在，但没有区域高精度叠图或 DTED；GUI 的粗略背景不是 Cesium，也不代表真实地形已验收。

## 4. 验收、失败尝试与限制

自动验收涵盖：其他工作目录、中文空格路径下实际构建和无界面运行、重复运行、缺失／损坏场景、缺失依赖、消息库哈希损坏、编译错误、端口占用，以及正式输入／产物和进程端口边界。以下批次十一组全部通过，验收入口退出 0；六类预期故障入口均明确失败，未发布失败产物。

| 证据 | 本轮结果 |
| --- | --- |
| 候选构建 | `g1-t04-build-20260917-162820-915606`；437 项输入哈希，737 个类、57 个资源 |
| OpenAMASE.jar SHA-256 | `D4E80C5318517266C161B636FDA4771FBD4921B71967E45F3C37C3A85E5E167E` |
| 独立探针 JAR SHA-256 | `282AE7688C395E7173403ADDF38B46CC272AF1737E562DA44652038EC08E2C25` |
| GUI 运行 | `g1-t04-run-20260917-162836-187500`；自动观察阶段两实体分别 38／37 条状态、41 条会话状态，随后暂停并保留 |
| 完整无界面运行 | `g1-t04-run-20260917-163024-703456`；两实体分别 1,481／1,480 条状态，1,484 条会话状态，最终 Stopped 时间为 `785009` 毫秒 |
| 无界面起止墙钟 | 16:30:24.703820～16:31:05.461956，含启动和收尾约 40.76 秒；进程退出 0，三个端口全部释放 |
| 自动套件 | `g1-t04-automatic-20260917-163023-871549`；十一组 passed，另核对 36 项进程／用户／机器环境值和执行策略未改变 |
| 原场景 SHA-256 | `AB44112D8151D7C24AC571DD6424F0FB3E236BDD85ABB5A5FDEE85B7EA1BEB0D`；副本未改变实体、任务或时长 |

两个实体源时间推进、经纬度实际变化；新库运行来源正确，UXTASK 版本为 8。无界面未出现窗口。785 秒终点因定时器离散步进观测到 785.009 秒，不是 UTC 时间。

| 已发生问题 | 处理及结果 |
| --- | --- |
| 验收插件初次编译失败 | 版本方法误写为 getSeriesVersion；改用真实接口 getLMCPSeriesVersion，重建通过 |
| 原无界面启动抛出 HeadlessException | 保留失败运行，修复两处显示依赖；完整仿真运行通过 |
| 第一次 GUI 退出出现探针日志写入异常 | 退出钩子和末尾事件并发；对日志关闭加同步和关闭状态，后续 GUI 正常退出 |
| GUI 与无界面共用实体端口 | 主端口不同仍在 9400／9500 冲突；新增显式 EntityPortOffset，运行副本分配独立实体端口并校验所有端口 |
| 子 PowerShell 异常输出编码混用 | 捕获线程按 UTF-8 解码系统编码失败；测试入口固定子进程 UTF-8，并保留原始输出字节后检查编码 |

原无界面失败记录为 `g1-t04-run-20260917-162016-205896`；首次修复后完整运行记录为 `g1-t04-run-20260917-162107-881269`；第一次自动套件失败记录为 `g1-t04-automatic-20260917-162511-853063`。它们不替代最终候选批次的验收。

人工确认：用户在 GUI 验收请求后回复“很好，继续”，按此回复完成验收收尾。确认原文及上下文记录在正式来源清单，未额外声称观察到了用户的每一次点击。

收尾批次为 `g1-t04-finalize-20260917-163948-623929`，入口退出 0。通过 AMASE 原有关闭路径结束 GUI，进程退出 0，5555／9400／9500 释放；此前无界面使用的 5556／19400／19500 同样未被本任务占用。正式目录成套发布，JAR 哈希与已验收候选一致，437 项输入重新核对通过，环境和执行策略未改变。

TCP 客户端读取真实状态归 T05；完整 AMASE↔UxAS 联调归 G3，C++ 与 Cesium 均未在本任务实施。G1 整体尚未完成。

## 5. 交接与归档

正式 AMASE JAR 的 SHA-256 为 `D4E80C5318517266C161B636FDA4771FBD4921B71967E45F3C37C3A85E5E167E`，可用默认启动入口读取。下次启动前核对正式 build-info.json、输入哈希及端口；不得使用 out/tmp 的隔离故障副本。

下一任务为 G1-T05：使用统一消息包解析 AMASE 实际 TCP 输出；须处理已确认的 Sentinel／属性外层，不能把本次内部事件证据当作网络验收。GUI 与无界面默认主端口都为 5555，单实例运行使用实体端口偏移 0；需要并行时明确指定另一组主端口与实体端口偏移。

实施、文档和日志按本次授权提交推送；实际提交标识与推送核验结果在工作日志收尾记录中登记。

完整过程见 [worklog.md](../worklog.md) 的 WL-20260917-008；当前执行状态见 [status](status.md) 和 [backlog](backlog.md)。
