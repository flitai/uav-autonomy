# G2-T03：Windows C++ LMCP 库验收

日期：2026-09-18，Asia/Shanghai。**G2-T03 已完成；T04 可执行、尚未启动，G2 尚未完成。**

从 G1 同批生成代码编译全部七模型，完成 C++／Java／Python 文件级双向验收并发布静态库。没有修改 MDM、生成器、模板或生成目录，没有重新生成消息，没有构建 UxAS、启动 AMASE 或进行双向网络联调。历史 G1／T02 报告保持原快照。

## 输入与构建

起点为 `1af7a91449b2159b672f094b343f72052bb00caf`，工作区干净。入口重新检查 T01 工具和 `Resolve-DepsPackage`，消费 T02 源码重建 `g2-t02-build-20260918-135426-199`／验收 `g2-t02-tests-20260918-140320-336` 的合格来源。LMCP 本身使用生成运行库及 C++ 标准库，无需链接第三方业务库；不为了形式上的依赖接入额外库。

G1 生成批次为 `g1-t03-20260917-152214-037296`。构建、验收及后续解析入口均检查生成器来源及输入、G1 父级 build-info.json、generation-info.json、Java JAR、七模型身份以及全部 1,013 个生成文件的哈希与集合。七模型版本仍为 CMASI 3、IMPACT 14、PERCEIVE 1、ROUTE 4、UXNATIVE 9、UXTASK 8、VEHICLES 1。

588 个 C++ 相关文件按清单复制到独立中文空格路径。根级 [CMakeLists.txt](../CMakeLists.txt)和 [LmcpSources.cmake](../cmake/LmcpSources.cmake)从已校验清单选择 **183 个库源文件**：164 个结构类、14 个系列 Factory／XMLReader、5 个运行库源文件。生成器附带 `test/` 中的三个测试程序不属于消息库；全部 382 个库头文件安装发布。入口显式构建 `uxas_lmcp`／`lmcp_probe` 并仅安装 `Lmcp` 组件；后续新增 UxAS 目标不会被本入口默认构建。CMake 配置还独立检查生成文件哈希和集合，拒绝过期或混合输入。

固定工具为 cl 19.44.35229／v143、工具目录版本 14.44.35207、SDK kit 10.0.26100.0、CMake 3.31.12、Ninja 1.13.2。主库使用 VS 2022、Release x64、`/std:c++14`、`/MD`，源码保持 C++11 兼容。实际命令、VC／SDK 搜索路径、编译器来源和库指令保存在本机运行记录。生成源码保留上游未使用参数及 size_t 窄化警告，未为消除警告改变生成语义。

## 标准入口与产物

在仓库根目录使用 PowerShell 5.1；Python 参数指向已验证的 3.14.7 x64，不安装工具：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-lmcp-cpp.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\lmcp-cpp.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<BUILD_RUN_ID>'
```

[build-lmcp-cpp.ps1](../scripts/windows/build-lmcp-cpp.ps1)只创建候选；[lmcp-cpp.tests.ps1](../tests/windows/lmcp-cpp.tests.ps1)验收后发布。两入口共用 [lmcp-cpp-common.ps1](../scripts/windows/lmcp-cpp-common.ps1)和 Python 标准库编排 [manage.py](../scripts/lmcp_cpp/manage.py)。每次启用工具后恢复进程环境、工作目录及输出编码，验证用户／系统 PATH 未变。生成锁与 G1 共用，另持有 T03 任务锁，避免生成替换和同时发布。

| 用途 | 路径 |
| --- | --- |
| 独立源码快照、VS 输出及候选 | `out/build/lmcp-cpp/<build-run-id>/消息 build/` |
| 命令、stdout／stderr、字段、样本与结果 | `out/runs/<run-id>/` |
| 正式包 | `out/artifacts/lmcp/cpp/<build-run-id>/<validation-run-id>/` |
| 当前合格指针 | `out/artifacts/lmcp/cpp/current.json` |
| 旧指针备份 | 同目录 `previous-<validation-run-id>.json` |

正式包含 `lib/lmcp.lib`、382 个头文件、3 个 CMake 包文件，共 386 个安装文件，另有独立 build-info.json。其输入清单关联 G1 父级、T02 依赖及本任务实现；不会改写 `out/artifacts/lmcp/build-info.json` 或 Java／AMASE 产物。

后续入口先调用解析函数；函数只返回一个已校验的包路径：

```powershell
. .\scripts\windows\lmcp-cpp-common.ps1
$lmcpPrefix = Resolve-LmcpCppPackage -PythonExecutable $pythonExe
```

CMake 消费形式为：

```cmake
find_package(UxasLmcp CONFIG REQUIRED NO_DEFAULT_PATH
    PATHS "${UXAS_LMCP_PREFIX}/share/UxasLmcp")
target_link_libraries(your_target PRIVATE Uxas::lmcp)
```

`your_target` 是后续工程目标占位符。包配置逐项校验安装文件；PowerShell 解析入口另核对当前工具、依赖、G1 输入、构建／验收身份、环境恢复和合格指针。配置不隐式构建或安装依赖。`UXAS_LMCP_VALIDATE_CANDIDATE` 仅供隔离验收消费候选，正式消费者不得以此跳过验收。根级构建文件或其他已登记输入变化后，旧包不会自动视为当前有效，需要重新构建／验收，不手改清单。

## 实际验收

| 记录 | 结果 |
| --- | --- |
| 首次构建 `g2-t03-build-20260918-142514-375` | 库源文件编译通过；新增探针错误使用 const getter，整个构建失败，不发布 |
| 修正后构建 `g2-t03-build-20260918-142636-015` | 干净目录构建、安装、x64／CRT 检查通过 |
| 首次验收 `g2-t03-test-20260918-142720-052` | 双向样本、164 类型、错误样本、VS／Ninja 消费、故障与迁移通过 |
| 最终构建 `g2-t03-build-20260918-143841-186` | 补齐模型集合检查及显式 LMCP 构建／安装目标后，全新输出重新构建通过 |
| 最终验收 `g2-t03-test-20260918-143927-259` | 六组验收全部通过，退出 0；原子更新合格指针，保留旧包及旧指针 |

最终 `lmcp.lib` SHA-256 为 `57C499DB03D4EC1A151F1187D04C00162EF862026688EED99E75DADC066D78F5`。这标识本批次产物，不宣称不同输出路径的 MSVC 静态库必然具有相同二进制哈希。

提交前补充实际头文件／库来源及返回值核对的中间批次为 `g2-t03-build-20260918-142827-601`／`g2-t03-test-20260918-142915-326`，同样通过；随后来源审查补齐 MDM 文件集合检查和显式构建目标，使用表中的最终批次重新验收，旧记录保留。

六组验收为：G1／T02 来源核对、三语言双向样本、六类错误样本、VS 安装包消费、六类来源故障与旧指针保护、Ninja 迁移包消费。另在构建入口核对全部源码、编译参数、库架构／CRT 指令与探针 DLL 依赖。

复用未修改的 [JavaProbe.java](../tests/lmcp/JavaProbe.java)、[python_probe.py](../tests/lmcp/python_probe.py)和 [samples.properties](../tests/lmcp/samples.properties)，新增 [C++ 探针](../tests/lmcp_cpp/probe.cpp)。新旧 Java JAR 分 JVM 使用；Java Sentinel 外层由既有方法取出，比较的是原始 LMCP。

| 样本 | 验证内容 | 每种校验模式的帧长度 |
| --- | --- | --- |
| basic AirVehicleState | ID 400、Time 1234567890123、位置、高度类型、航向、空速、空任务列表 | 188 字节 |
| wide AirVehicleState | ID 9007199254740993、关联任务 42／9007199254740995，超过 2⁵³ 的整数保持精确 | 204 字节 |
| TaskActive | UXTASK 8，TaskID 42、EntityID 400、TimeTaskActivated 1234567890123 | 51 字节 |

三个样本均覆盖零校验和与计算校验和。C++ 解码 Java／Python 后字段与重编码字节一致；C++ 独立构造的六帧由 Java／Python 读取，字段和完整字节一致；它们还与 G1 当时留存的 Java／Python 原始文件逐一对照哈希。int64 在 JSON 中使用字符串。C++ 工厂实例化全部 164 个结构类型，对照 Java 系列／类型／版本，并对全部默认对象做序列化往返。

坏校验和、计算校验帧截断、零校验帧截断、短头、误把 Sentinel 当原始 LMCP、旧 UXTASK 7 六种输入均以退出 2 和对应诊断拒绝。**严格帧长检查属于验收探针，未改造生成工厂为通用不可信数据解析器。** 原工厂允许零校验和；不能省略上层帧验证，也不能把这里的文件测试当作网络增量解码／双向兼容验收。

VS 与 Ninja 消费者在其他工作目录调用，构建目录包含中文空格，重复运行样本并检查 164 类型；正式包迁移后再消费通过。编译器实际读取的 LMCP 头文件、实际链接的 lmcp.lib 均来自对应 prefix：VS 使用 `/showIncludes`，Ninja 使用依赖数据库。库为 x64，编译 `/MD`，没有 Debug／静态 CRT 指令，探针只有允许的 Windows／动态 VC CRT DLL 依赖。沿用 T02 已验证的 Ninja 链接库路径处理，不扩大为任意工程布局保证。

隔离副本分别注入缺失库、损坏库、错误生成批次、输入哈希变化以及生成源码哈希变化、模型目录新增未登记文件，全部拒绝；生成源码哈希变化经真实 CMake 配置失败验证。未修改共享工具、正式生成目录或旧包。最终验收故障期间已有合格指针，确认其哈希保持不变；成功迁移后才原子替换。来源清单与原始失败诊断均保留。

## 交接

T04 从根级 CMake 接入 UxAS 构建图，继续核对 Makefile 的必需源码与服务注册；修改本任务构建输入时须重新建立有效 LMCP 批次。T03 不包含 UxAS、HelloWorld、AMASE↔UxAS 或完整重连。没有为当前任务改变生成器或消息语义，G1 原验收产物继续保持原哈希。

过程及归档见 [worklog](../worklog.md) 的 WL-20260918-007；当前状态以 [status](status.md)和 [任务清单](backlog.md)为准。
