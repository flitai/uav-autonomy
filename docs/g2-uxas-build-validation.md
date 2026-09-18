# G2-T05：Windows UxAS 候选构建验收

日期：2026-09-18，Asia/Shanghai。**T05 已完成，T06 可执行、尚未启动。** 本轮完成候选程序与平台验收，没有运行 HelloWorld、AMASE 或 WaterwaySearch，没有发布正式 UxAS 包；G2 尚未完成。

## 实现与入口

起点 `68ed420df4208305c99d7f25a6d0c45d652909ce`，工作区干净。没有安装工具或依赖，也没有改变模型、消息契约、规划算法、原 Makefile 或服务注册清单。

[Uxas.cmake](../cmake/Uxas.cmake) 在目标级增加 `DPSS_STATIC`、`NOMINMAX`，保留 `/EHsc`、C++14、Release x64、v143／14.44.35207、SDK kit 10.0.26100.0 和 `/MD`。122 个必需源码仍直接编入可执行目标；40 项服务注册和五个嵌入资源完整，CZMQ／TCP 保留，Zyre／串口关闭。依赖包的 CMake 缓存路径必须与合格 prefix 相符。

[程序清单](../OpenUxAS/src/cpp/Includes/uxas.manifest)嵌入 `activeCodePage=UTF-8`；[Windows 路径初始化](../OpenUxAS/src/cpp/Includes/UxAS_WindowsEnvironment.h)由 [main](../OpenUxAS/src/cpp/UxAS_Main.cpp) 在参数处理、文件访问、日志和工作线程前调用。它只向 Boost.Filesystem 的独立路径 locale 安装 `std::codecvt_utf8_utf16<wchar_t>`，不设置全局 locale，不改变数字和消息格式。依据为[微软进程 UTF-8 说明](https://learn.microsoft.com/en-us/windows/apps/design/globalizing/use-utf8-code-page)与 [Boost 1.74 path 实现](https://live.boost.org/doc/libs/1_74_0/libs/filesystem/src/path.cpp)。

构建和验收使用 [build-uxas.ps1](../scripts/windows/build-uxas.ps1)、[uxas-build.tests.ps1](../tests/windows/uxas-build.tests.ps1)，共用 [PowerShell 辅助入口](../scripts/windows/uxas-build-common.ps1)、[Python 编排](../scripts/uxas/build.py)及 [T04 来源检查](../scripts/uxas/graph.py)。PowerShell 5.1 标准命令，工作目录为仓库根目录：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-uxas.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-build.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>'
```

每次构建创建全新 `out/build/uxas/<build-run-id>/vs/`；候选目录为同批次的 `candidate/`，只含 `uxas.exe` 和 `build-info.json`。命令、工作目录、退出码、输入与工具哈希、File API、MSBuild 跟踪日志、对象、链接映射、警告和诊断位于构建目录及 `out/runs/<run-id>/`。构建前后重新核对来源，候选不是正式发布。

构建清单同时绑定独立平台探针的 SHA-256；验收前检查与该批次相符，每次运行前后再核对，并记录于验收 result 的 checks。验收写独立 `acceptance.json`，绑定构建编号、验收编号、候选清单及程序哈希。T06 内部使用以下只读接口复查后取得目录；函数输出流只有候选路径，诊断写主机流。以下片段供以 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File` 启动的本次脚本进程内部调用，不修改持久执行策略：

```powershell
. .\scripts\windows\uxas-build-common.ps1
$candidate = Resolve-UxasCandidate -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>' -ValidationRunId '<VALIDATION_RUN_ID>'
```

解析时要求构建和验收入口成功、环境恢复、收据匹配、当前工具／T02／T03／G1 和项目输入仍有效。源码或包来源变化后重新构建、验收；不能修改旧清单。T05 不更新 `out/artifacts/uxas/` 指针，也不捆绑或安装 CRT。

## 验收内容与证据

最终批次全部退出 0；入口从系统临时目录调用，编排又使用独立的其他工作目录。各批次记录均在 `out/runs/<编号>/`。

| 项目 | 编号／结果 |
| --- | --- |
| LMCP 重建／完整验收 | `g2-t03-build-20260918-172012-706`／`g2-t03-test-20260918-172109-035`；七模型、183 源码、164 类型、三语言样本及 VS／Ninja 迁移消费通过 |
| T04 配置／完整复验 | `g2-t04-configure-20260918-173529-088`／`g2-t04-test-20260918-173618-796`；构建图、10 个桥探针、15 项隔离故障通过 |
| T05 候选构建 | `g2-t05-build-20260918-173741-000`；普通路径干净构建通过 |
| T05 独立验收 | `g2-t05-test-20260918-173955-149`；中文空格路径干净构建、4 次平台探针、3 次启动前冒烟及 11 项隔离故障通过 |
| 候选解析接口复查 | `g2-t05-resolve-20260918-174200-479`；双编号解析、实时来源校验、单一路径输出和环境恢复通过 |
| 候选 exe SHA-256 | `67118CCB9A2A63C2A5FF4516D4C0FDE35D56C0529A160653F550BC641A40F096` |
| 候选 build-info SHA-256 | `323504DDC34D5E335849C209832FE31729B990CD514D14C4104E3C3ACBF5CE44` |
| LMCP 合格清单 SHA-256 | `DF81299DA715F78744AE67FBAB074615F184C3EB29EA16CE7FB2D5E8F44A0B33` |

`ordinary-build-audit.json`／`unicode-build-audit.json` 各记录 122 个对象、44 个实际链接输入库及哈希（含 25 个依赖库、1 个 LMCP 库和 MSVC／SDK 系统输入）。实际 VC DLL 为 14.50.35719.0，UCRT 为 10.0.26100.9444，与编译器 19.44.35229 分开登记；它们从本机 System32 加载，路径及 SHA-256 见 `*-loaded-modules.json`，版本见验收目录 `crt-versions.json`。没有安装或携带这些 DLL。

原始 MSBuild 日志包含末尾汇总的重复警告；构建审查记录按出现次数统计，不能当成唯一问题数量。最终合并 UxAS／平台探针日志的出现次数为 C4244 792、C4267 2296、C4018 8、C4101 4、C4554 2、C4996 4；不再出现 C4003、C4530 或 D9030。

- 完整构建核对 File API 的 122 个源码、40 项注册、五个资源，以及实际 122 个对象文件；链接映射保留全部服务名称。MSBuild `CL.command/read`、`link.command/read` 记录实际编译参数、头文件与静态库来源，拒绝混入其他 prefix。
- 依赖包共 27 个 `.lib`，顶层 25 个是当前导入目标的库，另两个为 `manual-link/boost_prg_exec_monitor-vc143-mt.lib`、`boost_test_exec_monitor-vc143-mt.lib`。UxAS 链接顶层 25 个及一个 LMCP 库。此前 T04 报告／WL-20260918-008 的“27 个依赖库加 1 个 LMCP 库”描述计数不准确；旧检查实际使用顶层 `lib/*.lib`，没有漏掉必需库。本条更正文字计数，历史报告保持。
- [平台探针](../tests/uxas_build/platform_probe.cpp)链接真实 FileSystemUtilities、FileLogger、Time 及其日志／配置依赖。验证 ACP 65001、中文参数、Boost UTF-8／UTF-16 往返、中文空格目录创建与枚举、XML 读写、真实中文文件日志、组合／排列正常值和溢出异常。
- 独立子进程分别使用 `TZ=UTC0` 与 `TZ=PST8PDT`，通过 `_get_timezone` 确认偏移 0／28800 秒；两个进程均核对同一 UTC 日期的 `1577934245678` 毫秒及一周换算，不修改系统时区、时钟。探针也核对全局 locale 不变。
- 检查 PE32+／x64、对象 `/MD` 指令、`/std:c++14`、`/EHsc` 和嵌入的实际程序清单。导入表仅允许 Windows 系统库和发布 CRT，拒绝静态／Debug CRT 及意外第三方 DLL。
- [加载观察器](../scripts/uxas/loader.py)只启动自己拥有的候选子进程，用 Windows 调试事件取得实际加载模块路径和哈希。未知参数 `-t05-unknown-中文` 必须输出原有 CLI 诊断并返回 DWORD `4294967295`（C++ `-1`）；不使用会继续启动的 `-version` 分支。此检查不启动服务，不计作 HelloWorld 或正常服务退出验收。
- 隔离副本覆盖缺失／损坏 exe、候选清单不匹配、依赖／LMCP 来源不符、工具及项目输入变化、过期模型输入、CMake 包缓存覆盖和受控超时。坏输入非零退出，超时只结束本次拥有的子进程；合格包和候选哈希前后保持。

普通与中文空格路径分别全量构建和运行探针，入口从其他工作目录调用；重复冒烟与入口环境恢复独立留证。重复不要求 PE 字节完全一致，验收收据绑定具体候选字节。

## 诊断、修正与限制

规划核查在忽略目录中先复现 DPSS 的 `dllimport` 定义错误。原源码已有 `DPSS_STATIC` 分支，正式修复只启用该分支。`NOMINMAX` 消除 Windows `max` 宏对 Permute 的干扰，没有改变组合计算。

规划中的一次命令行试验用 `-DCMAKE_CXX_FLAGS=/DDPSS_STATIC` 覆盖了默认 `/EHsc`，引入 C4530 和两个 Boost `throw_exception` 未解析符号。恢复默认异常选项后链接成功。这是诊断参数错误，不是新增工程缺陷；没有添加异常处理空实现。原始日志保存在 `out/runs/g2-t04-configure-20260918-155439-846/planning-*.log`，诊断目录不作为交付候选。

实施首批构建 `g2-t05-build-20260918-171558-917` 通过，独立诊断 `g2-t05-diagnostic-20260918-171915` 的平台与启动前检查通过。该批次使用 `/showIncludes`，实际出现 D9030：它禁用了 `/MP`。最终删除冗余 `/showIncludes`，使用 MSBuild 跟踪日志保留来源，再重建和复验前置批次及候选。旧结果保留，不改写其输入清单。新增探针的 `getenv` 弃用警告通过 Windows 环境读取 API 消除，没有全局屏蔽警告。

原有 C4244／C4267（转换）、C4018（符号性）、C4101（未用局部量）、C4554（运算优先级提示）和 C4996（旧接口弃用）分类保存，不在移植中整体重构。成功编译不证明这些潜在风险均已消除。

服务真实启停、HelloWorld 双向消息及完整主程序的关闭桥拒绝仍归 T06／T07；AMASE↔UxAS 的协议、来源过滤、WaterwaySearch 执行与完整重连归 G3／G4。候选构建和启动前检查不代表 G2 阶段完成。
