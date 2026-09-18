# G2-T07：原生 UxAS 复验、发布与阶段交接

日期：2026-09-18，Asia/Shanghai。**T01～T07 已完成，G2 验收通过；G3 尚未启动。** 本轮完成新输出中的完整重建、连续三次正常启停、中文路径构建和运行、隔离故障矩阵及正式发布。未启动 AMASE、WaterwaySearch 或外部 TCP 桥。

## 起点与来源

起点 `8f99ba28993f43ba94502d6c701806df91986187`，工作区干净，本地与远程 main 一致。复用 Python 3.14.7 x64 和 T01 固定工具。T02 固定依赖、T03 合格 LMCP 与 G1 七模型生成批次实时复核通过；本轮没有更改 CMake、模型、生成器、C++ 源码、依赖或原 HelloWorld XML。

| 环节 | 本轮编号／结论 |
| --- | --- |
| 全新普通路径构建 | `g2-t05-build-20260918-201846-291`；原 build-uxas.ps1 退出 0，干净输出中重新编译／链接 |
| T05 完整验收 | `g2-t05-test-20260918-202115-333`；退出 0，另在中文空格目录干净构建，平台／CRT／来源及 11 项隔离故障通过 |
| 新候选 T06 完整验收 | `g2-t06-test-20260918-202616-245`；退出 0，普通／中文运行、配置拒绝、13 个验收器反例及片段对照、辅助进程超时清理通过 |
| T07 完整验收 | `g2-t07-test-20260918-203915-916`；退出 0，10 个真实候选／包运行用例和 12 项隔离检查通过 |
| 正式发布 | `g2-t07-publish-20260918-204152-283`；退出 0，正式目录试运行通过后切换 current.json |
| 正式包独立运行 | `g2-t07-run-20260918-204325-360`；退出 0，真实消息与完整退出通过 |
| 正式包解析接口 | `g2-t07-resolve-20260918-204515-225`；退出 0，Resolve-UxasPackage 返回同一合格包目录 |

以上入口均从仓库以外的系统临时目录用脚本绝对路径调用；脚本和子进程工作目录分别记录。本轮干净重建的是 UxAS：复用来源合格的工具、依赖、LMCP 和下载缓存，没有声称从空缓存重建全部工具／依赖。先前同源码构建可重复成功，不承诺不同链接批次的 PE 字节完全相同。

沿用的 LMCP 构建／验收为 `g2-t03-build-20260918-195001-565`／`g2-t03-test-20260918-195057-347`，T04 为 `g2-t04-configure-20260918-195135-036`／`g2-t04-test-20260918-195240-495`；其输入未变。T01～T06 历史专题报告和来源清单原样保留，本页提供最新发布批次。

## 真实运行和故障矩阵

正常例复制原配置并核对哈希，保持 10 秒、1000／5001 ms、原两条文本，不传时长覆盖参数。每例使用参数数组、显式独立工作目录和 30 秒进程超时，日志／配置／stdout／stderr 全部归属本例。沿用 T06 验收器，从创建日志取得实际服务 ID，按配置顺序关联文本，要求两个方向的完整跨服务消息和全部生命周期证据；自收不算通过，ID 保存为字符串。

| 用例 | 进程单调耗时／退出码 | 结果 |
| --- | --- | --- |
| repeat-1 | 12.205 秒／0 | 双向消息、按时长关闭、服务终止完成；无强制终止，已回收 |
| repeat-2 | 12.216 秒／0 | 双向消息、按时长关闭、服务终止完成；无强制终止，已回收 |
| repeat-3 | 12.223 秒／0 | 双向消息、按时长关闭、服务终止完成；无强制终止，已回收 |
| 中文 空格运行 | 12.214 秒／0 | 双向消息、按时长关闭、服务终止完成；无强制终止，已回收 |
| missing-configuration | 0.013 秒／100 | 预期失败已验证；原进程记录保持 failed，已回收 |
| malformed-configuration | 0.013 秒／100 | 预期失败已验证；原进程记录保持 failed，已回收 |
| disabled-serial | 0.014 秒／300 | 预期失败已验证；原进程记录保持 failed，已回收 |
| disabled-zyre | 0.013 秒／300 | 预期失败已验证；原进程记录保持 failed，已回收 |
| uxas-timeout | 30.015 秒／1 | 预期失败已验证；原进程记录保持 failed，已回收 |
| staged-package | 12.234 秒／0 | 双向消息、按时长关闭、服务终止完成；无强制终止，已回收 |

前三例是同一新候选连续运行，每次正常退出并回收后才启动下一次；两方向的观察计数记录在 messages.json，不要求严格条数／周期。中文例直接运行 T05 中文路径中编译的 exe，依据该批 unicode-loaded-modules.json 绑定哈希，运行目录也含中文空格；不是仅重命名普通路径产物。

缺失／损坏 XML 均返回 100，关闭的串口／Zyre 请求均返回 300；诊断包含本例路径或桥类型及 OFF 开关，并确认网络服务器／HelloWorld 尚未创建。超时例只在隔离副本将时长改为 60 秒，真实 UxAS 已启动且收到消息，30 秒等待到期后仅终止持有句柄的本次进程，记录 timedOut／forcedTermination／非零退出并回收。原配置和正常运行规则保持不变。

12 项隔离检查包括依赖静态库缺失／损坏、LMCP 混批、G1 生成身份不符、正式包 exe 缺失／损坏、清单损坏、CRT 缺失／损坏，以及指针替换前失败、替换后提交失败回滚、首次发布失败恢复无指针。直接调用生产来源校验器与指针事务，详细实现见 [隔离检查](../tests/uxas_release/checks.py)。依赖库为静态链接，缺失／损坏验证的是消费前来源拒绝；CRT 故障也使用副本检查，未移除系统 DLL，不冒称 Windows 加载器故障试验。回滚测试的旧包是合格候选的隔离副本；本轮是首次正式发布，原先没有正式 UxAS 指针。

preservation.json 记录既有候选、依赖／LMCP 指针、生成元数据和正式 Java／AMASE 的前后哈希；源码及完整合格依赖／LMCP 包另由 Resolve-UxasCandidate 和运行后复查保证。所有正常例、配置拒绝和超时例均回收本次进程；入口恢复环境、工作目录、控制台编码，用户／系统 PATH 未变。

首次 T07 验收 `g2-t07-test-20260918-203132-962` 在上述三次运行、中文路径、配置拒绝和真实超时通过后，于打包阶段失败：新脚本假定 T05 每批都会产生 crt-versions.json，实际新 T05 保存的是 loaded-modules.json 中的加载路径和哈希。失败记录保留，未发布。修正为从同批 ordinary-loaded-modules.json 绑定实际候选及四个 CRT，核对当前文件哈希后用 Windows 固定版本资源生成本包的版本清单，并保留原加载记录。隔离打包预检通过后重新执行完整 T07；只修改独立发布脚本，没有改写旧清单或重用失败收据。

## 正式包与使用命令

[发布入口](../scripts/windows/publish-uxas.ps1)、[正式运行入口](../scripts/windows/run-uxas-release.ps1)和 [T07 验收入口](../tests/windows/uxas-release.tests.ps1)共用 [PowerShell 编排](../scripts/windows/uxas-release-common.ps1)、[发布编排](../scripts/uxas_release/release.py)和 [来源／事务模块](../scripts/uxas_release/package.py)。新脚本放在独立 scripts/uxas_release、tests/uxas_release，单独登记输入；保留 T05／T06 已验收来源规则及候选命令。

正式包位于 `out/artifacts/uxas/g2-t05-build-20260918-201846-291/g2-t07-test-20260918-203915-916/g2-t07-publish-20260918-204152-283/`，`out/artifacts/uxas/current.json` 原子指向该包。包内有 exe、原 XML、候选／生成／CRT 来源副本、handoff.json 和许可证文件；清单关联 T05 双编号、T06 收据、T07 验收及全部包文件和运行脚本哈希。包与候选 exe 完全一致：

- exe SHA-256：`CDE0AB551D557A7E469645D8144ECA652EEF62717934C4F91A0FF8BDEE115C7C`。
- 候选清单 SHA-256：`E14D4F504C066FBE51F8FB4F027B9871F80B42A08DE1AE88AD220FA33DEEA526`。
- 正式包清单 SHA-256：`D664760FA8E30A717B19AE01E06F0A3F2A473C6304AFAD4C3174DECC679702F5`。
- T07 验收收据 SHA-256：`68869351EE4FA1400C91C659CF05932B6D16C9A1D6E268173658923B87ED4CAA`。

发布先验证 T07 收据、全部运行证据和实时输入，再复制到新的正式批次目录，实际运行该位置的程序；PowerShell 恢复成功后才提交指针。已有指针保留 previous 备份；事务失败恢复旧字节，旧包和失败目录保留。发布后另以首次失败的 T07 编号调用公开发布入口：`g2-t07-publish-20260918-204335-608` 返回 1，因无合格收据被拒绝，实际正式指针哈希前后相同且环境恢复；结果另记 out/tmp/g2-t07-rejected-publication.json。消费入口复查当前指针、发布结果、T07／T06 收据、候选来源、配置／程序和当前 CRT；来源改变需重建或重新验收，不改写旧清单。这是开发工作区内的合格发布，仍依赖现有来源记录；独立安装包和第二机器部署归 G8。

PowerShell 5.1，在仓库根运行正式 HelloWorld：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-uxas-release.ps1 -PythonExecutable $pythonExe
```

正式运行只支持默认 HelloWorld，不再手填候选编号；日志在独立 `out/runs/g2-t07-run-<时间>/`。已有 run-uxas.ps1 仍可用本页 T05 双编号运行候选。重新验收／发布的完整顺序如下，每步必须退出 0 并从该次结果取得新编号：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-uxas.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-build.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-helloworld.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>' -ValidationRunId '<VALIDATION_RUN_ID>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-release.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>' -ValidationRunId '<VALIDATION_RUN_ID>' -HelloWorldRunId '<HELLOWORLD_TEST_RUN_ID>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\publish-uxas.ps1 -PythonExecutable $pythonExe -ReleaseRunId '<T07_TEST_RUN_ID>'
```

脚本消费正式路径时，在以 `powershell.exe -NoProfile -ExecutionPolicy Bypass` 启动的进程内点入 `scripts/windows/uxas-release-common.ps1`，调用 `Resolve-UxasPackage -PythonExecutable $pythonExe`；它会完成来源复查，不应只读取 current.json 后跳过校验。不永久更改执行策略。

## G2 结束检查与 G3 输入

| 阶段检查 | 已核实结论／证据 |
| --- | --- |
| T01 工具及 T02 固定依赖 | 历史完整验收保留，本轮实时来源、编译、加载记录复核有效；见 [T01](g2-cpp-toolchain-validation.md)、[T02](g2-dependencies-validation.md) |
| T03 消息与 T04 构建图 | 七模型同批来源、122 编译单元、40 项服务、5 个资源保持；见 [T03](g2-lmcp-cpp-validation.md)、[T04](g2-uxas-cmake-validation.md)及本页批次 |
| T05 完整构建／T06 内部消息 | 本轮新批次分别完整复验，正常退出和真实双向消息通过；历史见 [T05](g2-uxas-build-validation.md)、[T06](g2-uxas-helloworld-validation.md) |
| T07 重复、路径、故障与发布 | 本页各矩阵和正式独立运行通过；正式 exe 与候选哈希一致，已有合格产物保持 |
| 文档与来源交接 | 本报告、status、backlog、总体计划、G2 方案、AGENTS、工作日志同步；原始日志在忽略目录 |

G3 接收本页正式包、同批七模型 `g1-t03-20260917-152214-037296`、上述 C++ LMCP 和既有 AMASE `g1-t04-build-20260917-162820-915606`；本轮只读复查 AMASE 的输入、JAR、LMCP 和原人工验收／退出记录，没有重新启动仿真。服务／桥清单和来源摘要保存于正式包 handoff.json：TCP／CZMQ 保留，Zyre／串口关闭，必需任务服务和 AutomationDiagramDataService 保留。只验证了 HelloWorld 的内部消息，不代表全部服务功能通过。

四项动态 CRT 的实际路径、版本和哈希来自新 T05 加载检查，发布和启动时继续复核；不捆绑 CRT。MSVC 三项为 14.50.35719.0，UCRT 为 10.0.26100.9444。包内保留 OpenUxAS 许可及固定依赖 copyright 文本；不把源码／缓存副本作为正式程序发布。

后续 G3 先细化双向封装、来源过滤、启动顺序、实时状态及 WaterwaySearch 真实规划命令执行；完整重连、重置分段、真实地形、Cesium、训练和 G8 第二机器／离线演示仍待对应任务。AMASE GUI 的 5555／9400／9500 与无界面 5556／19400／19500 沿用显式隔离约定。**本轮止于 G2，不执行 G3。** 归档结果见 [worklog](../worklog.md)。
