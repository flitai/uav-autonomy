# G2-T02：Windows 原生第三方依赖验收

## 范围与入口

本任务固定并构建第三方依赖，验收真实功能、来源、Release x64／动态 CRT 和可迁移消费。LMCP、UxAS、HelloWorld 与仿真运行属于后续任务。

工作目录为仓库根目录；入口兼容 PowerShell 5.1，自行启用并恢复 T01 工具环境：

```powershell
# 全新候选；禁止读取二进制缓存，仍复用经过校验的源码下载。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-deps.ps1 -Rebuild
# 使用实际成功构建的候选编号。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\deps.tests.ps1 -BuildRunId '<BUILD_RUN_ID>'
# 后续重复准备可读取匹配 ABI 的本地二进制缓存。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-deps.ps1
```

构建失败不能继续用旧产物宣称本次成功。构建只生成候选；全部验收通过后，才原子替换 `out/artifacts/deps/current.json`。各次正式包独立保留，读取指针后还须核对 `build-info.json` 哈希、输入和文件清单、验收记录。配置 CMake 不会下载或安装依赖。

## 固定来源与兼容处理

- [manifest](../vcpkg.json)、[registry 配置](../vcpkg-configuration.json)、[来源清单](../config/windows-dependencies.json)固定 vcpkg checkout／baseline `9e593bb18ea69cc5095e012465dcd675a822ed0d`。
- [triplet](../config/vcpkg/triplets/x64-windows-uxas.cmake)固定 Release、静态库、动态 CRT、v143／14.44.35207、SDK kit 10.0.26100.0、C++14。消费者关闭 Boost 自动链接，显式传递库。
- Boost 沿用历史模块 ports：81 个直接及传递 ports 的历史 tree、版本和 port-version 均在清单中，辅助配方以 overlay 承载必要修复。业务库仍为 1.74.0；默认图不含 Zyre／serial。
- libzmq 4.3.1 保留 TCP／STREAM 和内置 TweetNaCl CURVE，关闭 drafts、OpenPGM、VMCI、示例及文档；cppzmq 4.2.2 的静态目标传递同一 libzmq。
- CZMQ 4.0.2 保留完整稳定库及 `zframe_*`，补齐静态宏和 Windows 系统库；关闭 drafts、工具／自测与可选外部依赖。
- pugixml 1.12.1 将原 Anod `as_int64` 补丁转换为统一 diff，保持窄字符行为：缺失属性返回默认值，空值／非法文本返回 0；未重新定义解析语义。
- SQLite 使用官方 `sqlite-autoconf-3390400`（3.39.4），列元数据／线程安全开启。SQLiteCpp 1.3.1 使用外部 SQLite，移除旧 CMake 中追加的 `/MT`，统一 `/MD`，关闭辅助分析、示例和上游测试。
- 固定 vcpkg 的 SPDX 辅助函数使用了 CMake 4.x 的 JSON 编码功能；项目 triplet 引入兼容实现，保留 3.31.12 及原始 vcpkg checkout。独立探针检查中文、引号、反斜线与控制字符的 JSON 往返。
- Boost.Build 1.74 的 v143 识别、固定编译器路径、库名后缀、带空格 include，以及 Windows 窄字符 API／响应文件编码由辅助 overlay 修复。b2 使用进程 UTF-8 manifest，MSVC 响应文件在写入时仅添加一个 BOM；不改变系统区域设置。[微软进程 UTF-8 说明](https://learn.microsoft.com/en-us/windows/apps/design/globalizing/use-utf8-code-page)
- 主机辅助工具固定为 PowerShell 7.6.3、7-Zip／7zr 26.02、pkgconf 2.5.1-1 和 MSYS2 runtime 3.6.5-1；来源来自固定 vcpkg 元数据。PowerShell／7-Zip 强制获取固定便携版本，检查归档哈希、关键文件、版本和完整安装收据。仅获取这两个工具时切换下载设置，随后恢复强制系统二进制模式并再次确认 CMake／Ninja 路径；不使用系统 7-Zip 作为最终基线。

版本选择依据 [vcpkg 版本规则](https://learn.microsoft.com/en-us/vcpkg/users/versioning)、[overlay 解析规则](https://learn.microsoft.com/en-us/vcpkg/concepts/package-name-resolution)和 [triplet 配置](https://learn.microsoft.com/en-us/vcpkg/users/triplets)。overlay 的源码哈希、配方和补丁纳入版本管理，不把 baseline 视为 overlay 的版本锁。

## 消费接口与证据

`UxasDependenciesConfig.cmake` 提供 `UxasDeps::{zeromq,cppzmq,czmq,pugixml,sqlite3,sqlitecpp,boost}`。以合格指针解析出的 prefix 调用 `find_package(UxasDependencies CONFIG REQUIRED NO_DEFAULT_PATH PATHS "${prefix}/share/UxasDependencies")`。导入目标封装头文件、静态宏、库和系统依赖，路径相对包自身解析；当前只验收 Release x64。

候选位于 `out/build/deps/<编号>/依赖 build/installed/x64-windows-uxas/`；原始记录位于 `out/runs/<编号>/`；故障副本位于 `out/tests/`。正式包通过 VS／Ninja 迁移消费后才更新指针。`.tools/` 保存源码下载、辅助工具及二进制缓存；这些目录均不进入 Git。

每批来源记录保存工具／输入哈希、历史 port tree、overlay／补丁、实际命令与工作目录、退出码、vcpkg 安装状态、源码 SPDX、缓存行为和安装文件哈希。探针保留 `/showIncludes`、`/VERBOSE:LIB`、PE／库指令和实际 CRT 模块证据。

后续 Windows 入口可点入 `scripts/windows/deps-common.ps1`，调用 `Resolve-DepsPackage` 取得当前合格 prefix；该函数核对指针、构建／验收身份、输入清单及哈希、安装文件清单及哈希。修改配方、清单或验收输入后必须重新建立合格记录，不能直接复用旧指针。

## 已确认的消费兼容细节

- pugixml 发布标签为 1.12.1，但上游 `PUGIXML_VERSION` 仍为 1120（1.12 API）；发布版本由固定源码摘要证明，不能误用 1121 的静态断言。
- SQLiteCpp 1.3.1 使用 `SQLITE_OPEN_*` 和 `Column::getText()`，探针按旧版 API 编写，没有为了新 API 升级依赖。
- CZMQ 4.0.2 头文件公开了旧 MSVC 的 `snprintf` 宏。综合探针在包含 CZMQ 后取消该宏，避免污染随后包含的 Boost C++ 头；未修改 CZMQ 的字符串处理实现。UxAS 实际 include 顺序／宏适配由 T05 处理。
- CMake 3.31／Ninja 在长链接行下生成无 BOM 的 UTF-8 响应文件，MSVC linker 会按本地代码页读取中文库路径。验收工程设置 `CMAKE_CXX_USE_RESPONSE_FILE_FOR_LIBRARIES=OFF`，将库路径保留在 Unicode 命令行；响应文件中的探针对象名为相对 ASCII。此设置可由 [CMake 3.31 源码](https://github.com/Kitware/CMake/blob/v3.31.12/Source/cmNinjaNormalTargetGenerator.cxx)核查。G2 主工程仍采用 VS 2022，未修改固定 CMake／Ninja 二进制；更长命令及任意工程布局不在本次探针覆盖范围。
- PowerShell 5.1 的 `Get-Content -Raw` 返回值带 provider 附加属性，直接深度序列化会展开大量元数据；记录文本改用 `File.ReadAllText`。短进程先保留 native handle 再等待，以可靠取得退出码；null 退出码不算成功。

## 实际结果

2026-09-18（Asia/Shanghai），T02 已完成；T03 可执行、尚未启动。

| 记录 | 实际结果 |
| --- | --- |
| 源码重建 `g2-t02-build-20260918-135426-199` | 13:54:26～13:56:10，退出 0；`-Rebuild`、全新中文空格目录，两个阶段缓存读取均为 0；89 个 ports、27 个静态库、10,602 个安装文件 |
| 首次完整验收 `g2-t02-tests-20260918-135907-382` | 13:59:07～14:00:25，退出 0；11 组全部通过，四个新消费工程（VS／Ninja × 候选／正式迁移包），16 次 CTest 加 16 次直接功能运行全部通过 |
| 最终重复验收 `g2-t02-tests-20260918-140320-336` | 14:03:20～14:04:37，退出 0；11 组再次通过，32 次功能运行全部成功；已有合格包时故障不改写旧指针，迁移成功后原子更新当前指针并保留旧指针备份 |
| 缓存复建 `g2-t02-build-20260918-135828-266` | 退出 0；两个阶段分别恢复 8、81 个包；输入一致，全部 10,602 个安装文件与源码重建批次 SHA-256 一致；对照收据为 `out/tmp/g2-t02-cache-comparison.json` |

功能证据覆盖：cppzmq／CZMQ 的二进制、空帧、多帧双向互操作；本机 TCP STREAM 的连接身份帧／空通知、二进制收发及清理；CURVE 能力；pugixml 大于 2⁵³、正负 int64 边界、缺失默认值及原空／非法行为；Boost 四模块功能、几何面积／有效性、图最短路径、130 位 DynamicBitset；SQLiteCpp 建库、事务提交／回退、重新打开数据库、64 位整数、UTF-8 文本、二进制及列来源元数据。

VS／Ninja 均从其他工作目录配置、构建、运行，Ninja 输出目录含中文和空格；依赖构建及候选消费 prefix 也含中文空格。编译期断言与命令核对为 x64、C++14、Release `/MD`，27 个静态库无禁止 CRT 指令，消费者无第三方业务 DLL／Debug CRT。实际加载 VC DLL 为 14.50.35719.0，UCRT 为 10.0.26100.9444，均来自系统目录；与编译器版本分开记录，不降级共享运行库。Ninja 会吸收 `/showIncludes` 输出，因此通过 `ninja -t deps` 的真实依赖数据库解析相对路径后核对头文件来源。

故障只在副本注入：缺失／损坏库、源码 SHA-512 不符、修改工具清单／配方、错误 triplet 元数据，以及探针超时，均明确拒绝；只结束本次超时探针 PID。原始记录和旧包保留，进程环境及用户／系统 PATH 未持久改变。首次没有旧指针时确认失败不创建指针，后续复验同时检查已有合格指针不被故障检查改写。

## 排查记录与交接限制

首次实现遇到的失败均保留在 `out/runs/g2-t02-*`：缺少固定 PowerShell 主机工具、vcpkg 子进程清理 PATH 后找不到 Ninja、CMake 3.31 不支持 SPDX 的新编码调用、libzmq 许可证文件名错误、Boost v143／编码／库名差异。分别通过固定辅助工具、triplet 传递受控 PATH、SPDX 兼容函数、正确安装 COPYING／COPYING.LESSER，以及有限 Boost 辅助配方修复解决。

`133855-877` 的所有 ports 已安装，但 PowerShell provider 元数据展开导致记录进程异常耗时；只停止了核对过命令行的本任务记录进程，保留安装目录并登记 failed。`134551-953` 因直接／传递允许清单未去重而拒绝登记，修正计数后重新构建。`135216-386` 重建期间验收进程辅助函数发生修改，输入哈希防线如实拒绝该批次，随后以输入稳定的 `135426-199` 全新重建取代；没有回写旧清单。

重复验收 `g2-t02-tests-20260918-140053-860` 的 11 组检查通过，但最后更新已有指针时 `.NET File.Replace` 收到 PowerShell 5.1 将 `$null` 转换的空备份路径，退出 1；旧指针及旧包保持。改为唯一的真实备份路径后，最终批次 `140320-336` 成功更新。该失败批次仍为 failed，不因探针通过而改写其结论。

探针开发中的旧版 API／宏假设、路径分隔符、Ninja 吸收并相对化头文件路径、短进程 null 退出码、Ninja 中文响应文件问题均经过真实失败定位并修正；没有将单纯编译、CTest 文本或旧程序输出当作整套通过。

后续先通过 `Resolve-DepsPackage` 验证当前合格包，再实施 T03 的七模型 C++ LMCP 编译及跨语言样本。尚未编译 LMCP／UxAS，未运行 HelloWorld／AMASE，未验证 UxAS 协议或算法；本次不登记 G2 阶段完成。CZMQ 宏与 Ninja 更长链接行的限制见上节。所有版本、工具及失败诊断保留，不自动卸载共享组件。
