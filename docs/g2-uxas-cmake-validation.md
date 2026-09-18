# G2-T04：Windows UxAS CMake 构建图验收

日期：2026-09-18，Asia/Shanghai。**G2-T04 已完成；T05 可执行、尚未启动。** 本任务通过配置、构建图审查和独立 C++ 桥配置探针；没有完整编译或运行 UxAS，G2 尚未完成。

## 范围与构建入口

起点 `0366169c207f9832850b2dceaa8975ef720b04ed`，工作区干净。未安装依赖、改变消息模型或任务算法；原 Makefile 和服务注册文件保持不变。入口为 [configure-uxas.ps1](../scripts/windows/configure-uxas.ps1)、[uxas-cmake.tests.ps1](../tests/windows/uxas-cmake.tests.ps1)，共用 [PowerShell 辅助实现](../scripts/windows/uxas-cmake-common.ps1)和 [Python 编排与来源校验](../scripts/uxas/graph.py)。

仓库根目录中的标准命令（PowerShell 5.1；Python 使用已验证的 3.14.7 x64）：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\configure-uxas.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\uxas-cmake.tests.ps1 -PythonExecutable $pythonExe -ConfigureRunId '<CONFIGURE_RUN_ID>'
```

配置入口只写 `out/build/uxas/<run-id>/` 和 `out/runs/<run-id>/`，结果为 `configured`，不是编译成功或正式 UxAS 发布。验收只构建 `bridge_configuration_probe`、`bridge_legacy_defaults_probe`，这两个目标不属于默认全部构建。命令、工作目录、退出码、原始 stdout／stderr、输入哈希、工具、包来源及环境恢复均留存；失败保留记录和旧合格包。

[根 CMake](../CMakeLists.txt) 的 `UXAS_BUILD_EXECUTABLE` 默认 OFF，保持独立 LMCP 构建；[windows-uxas-release 预设](../CMakePresets.json)设为 ON。使用 VS 2022、Release x64、v143／14.44.35207、SDK kit 10.0.26100.0、C++14／动态 CRT。配置检查实际 CMake、cl 和 link 路径与已校验工具相符。预设缺少合格来源上下文时失败；CMake 回调实时校验 T02、T03、G1 和项目输入，不隐式安装依赖。

## 源码与链接图

[显式清单](../config/uxas-sources.json)对照 [Makefile](../OpenUxAS/Makefile)：14 个源码／包含目录，加主入口，共 **125 个编译单元**。默认仅排除串口桥、LmcpObjectNetworkZeroMqZyreBridge 和 ZeroMqZyreBridge 三个实现，**122 个源码直接加入 uxas 可执行目标**。配置检查实际目录、文件集合、重复项和服务注册，新增源码必须显式审查清单。

保留 [00_ServiceList.h](../OpenUxAS/src/cpp/Services/00_ServiceList.h) 的 **40 项服务注册**、全部任务／规划／日志、SerialAutomationRequestTestService 和 SentinelSerialBuffer。AutomationDiagramDataService 的实现位于 `src/cpp/Services/`；`resources/AutomationDiagramDataService/` 当前没有 `.cpp`，其五个 `.code` 嵌入文件作为资源进入目标并核对引用和哈希，目录其余资源也登记来源。

消费合格 `Uxas::lmcp`，构建图没有重复的 `uxas_lmcp`／`lmcp_probe`。链接 T02 的 `UxasDeps::zeromq`、`cppzmq`、`czmq`、`pugixml`、`sqlite3`、`sqlitecpp`、`boost`；实际图引用 27 个 T02 静态库及一个 LMCP 库，头文件来自对应合格 prefix。`BOOST_ALL_NO_LIB`、`CZMQ_STATIC`、`ZMQ_STATIC` 和 Windows 系统库沿目标传递；图中不含 Zyre／serial 链接库或 Linux dl／pthread 参数。

配置创建 CMake File API `codemodel-v2` 查询，保存原始 reply、`uxas-graph.json`、`uxas-inputs.cmake` 和 `graph-audit.json`。审查实际生成的源码、资源、包含目录、定义、C++14、链接路径及 vcxproj 的 `/MD`；来源清单与实际图共同验收。它们不能代替完整编译／链接证据。[预设文档](https://cmake.org/cmake/help/v3.31/manual/cmake-presets.7.html)、[File API 文档](https://cmake.org/cmake/help/v3.31/manual/cmake-file-api.7.html)

## 可选桥行为

`UXAS_ENABLE_SERIAL`、`UXAS_ENABLE_ZYRE` 默认 OFF；当前依赖没有合格可选库，任一请求 ON 时 CMake 返回 1 并说明原因。数值条件编译覆盖源码、桥头文件、Zyre 包装工具、串口类型头和实例化分支；未定义这些宏时仍默认为 1，保持原 Makefile 行为。

[共享能力检查](../OpenUxAS/src/cpp/Communications/BridgeBuildCapabilities.h)只读取桥类型，不创建网络或服务。主程序在配置加载之后、内部网络启动之前检查，关闭桥请求返回原错误码 300；桥管理器在批量创建前返回 false，单桥创建也防御性拒绝。未扩展成通用 XML／桥配置校验，保留桥的完整初始化与网络行为仍需后续真实程序验证。

独立探针直接编译上述生产头文件，并包含全部被关闭的可选头文件以验证条件编译。原 HelloWorld XML 保持 10 秒、1000／5001 ms 配置，仅在本任务读取，不启动服务。默认宏探针仅验证未定义开关时的能力判断，不宣称旧 Makefile 或可选依赖已编译。

## 实际验收

| 项目 | 本次证据与结果 |
| --- | --- |
| 最终 LMCP 重建／复验 | `g2-t03-build-20260918-151142-342`／`g2-t03-test-20260918-151229-483`，入口退出 0；完整沿用 T03 六组验收，183 个源文件、164 类型、三语言字节、坏帧拒绝和 VS／Ninja 迁移消费通过 |
| 最终 UxAS 配置 | `g2-t04-configure-20260918-151514-768`，入口退出 0，状态 configured；VS Release x64 构建图通过 |
| 最终 T04 验收 | `g2-t04-test-20260918-151556-601`，入口退出 0，状态 passed；未生成 uxas.exe |
| 路径与重复 | 从其他工作目录调用两个 PowerShell 入口；中文空格输出目录内配置、重复配置、编译探针并运行；三次 File API 审查均通过 |
| 桥探针 10 例 | 原 HelloWorld、TCP、SUB/PUSH、PUB/PULL、Impact SUB/PUSH 返回 0；串口、Zyre、混合请求返回 300 且记录对应类型／开关；坏 XML 返回 100；旧宏缺省探针返回 0、serial=1／zyre=1 |
| 隔离故障 15 例 | 两个开关 ON、缺失来源上下文、依赖／LMCP 来源不符、工具来源变化、缺失源码、缺失资源、新增源码、重复源码；CZMQ 库、LMCP 库、生成源码、嵌入资源和 MDM 输入副本哈希损坏全部拒绝 |
| 回退与环境 | 故障只改副本；原依赖／LMCP 指针哈希未变，正式包未覆盖；两个入口恢复进程环境、工作目录和输出编码，用户／系统 PATH 未变 |

十项配置故障通过真实 CMake 返回 1；五项文件损坏调用生产来源校验函数的独立 CLI，返回 1 并记录具体哈希错误，不能将后者描述成完整 UxAS 故障运行。全部原始记录在 `out/runs/`，不提交生成物或本机绝对路径。

T02 仍为 `g2-t02-build-20260918-135426-199`／`g2-t02-tests-20260918-140320-336`；G1 仍为 `g1-t03-20260917-152214-037296`。新 LMCP build-info SHA-256 为 `5ABC0F28733C9D0E6F26E74C16083FED7EF4139E1097A940ED26468F2C903171`。本次只更新独立 C++ 合格批次，未改写旧清单或 Java／AMASE 历史证据；[T03 报告](g2-lmcp-cpp-validation.md)保留原任务快照，本页记录后续复验。

## 调整与交接

首次配置 `g2-t04-configure-20260918-150947-051` 被过严的 CMake 次版本变量检查拒绝。实际 cl 路径为 14.44.35207；CMake 对默认工具目录将 `CMAKE_VS_PLATFORM_TOOLSET_VERSION` 留空。修正为核对生成器工具集参数及实际工具路径，没有放宽编译器／SDK 版本。此前 LMCP 重建 `g2-t03-build-20260918-150806-612`／`g2-t03-test-20260918-150856-255` 已通过；修正 CMake 后另行完整重建／复验，旧记录均保留。

首次 T04 验收 `g2-t04-test-20260918-151352-512` 的桥探针全部通过，但 CMake 拒绝 Zyre ON 时诊断自动换行，使逐字匹配误判。仅对断言文本规范化空白，原始日志保持；新配置和上述最终验收重新执行并通过。

**T05 下一步**：复查来源后，从干净输出实际构建全部 UxAS，根据真实错误处理 Windows 平台与旧依赖兼容问题；不能删减服务绕过失败。完整主程序的启动前拒绝、HelloWorld 双向消息与正常退出归 T06／T07；双向协议、来源过滤与 WaterwaySearch 归 G3。此次不进入上述任务。
