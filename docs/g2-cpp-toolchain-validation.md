# G2-T01：Windows C++ 工具链实施与验收记录

日期：2026-09-18，Asia/Shanghai（UTC+08:00）。状态：**G2-T01 已完成。来源阻塞已解除，MSVC／SDK 已安装，十组完整验收通过；T02 可执行，尚未启动。** 首次实施起点为 `48c4d6bed9ef09bc06be24b8b56ea355f0a59fd8`，当时工作区干净。用户已授权实施 T01，并选择微软安装器的系统默认目录。

第 1～5 节保留 11:08～11:34 首次实施的部分完成快照；后续修复、安装与最终结论见第 6 节，不将后续结果回写为首次已通过。

## 1. 已落地内容与边界

- [固定工具清单](../config/windows-cpp-toolchain.json)：版本、完整提交、下载地址、SHA-256、微软组件 ID、来源与许可入口。
- [准备入口](../scripts/windows/setup-cpp.ps1)、[环境入口](../scripts/windows/use-cpp.ps1)和 [公共实现](../scripts/windows/cpp-common.ps1)：PowerShell 5.1、脚本相对路径、缓存与安装文件校验、进程环境恢复、独立运行记录、失败不覆盖旧工具。完整模式的安装及环境启用分支尚待真实 MSVC 验证。
- [验收入口](../tests/windows/cpp-toolchain.tests.ps1)和 [独立探针工程](../tests/cpp_toolchain/CMakeLists.txt)：C／C++、Windows API、固定宽度整数、线程、Release x64／动态 CRT；配置 Visual Studio 2022 与 Ninja 两种生成器。探针源码已创建，尚未编译运行。
- CMake、Ninja 和 vcpkg 已实际准备于被忽略的 `.tools/`。未启动微软安装器，未安装 MSVC／SDK，未触发 UAC 或重启；未修改用户／系统 PATH，未执行全局 vcpkg 集成。
- 没有安装第三方业务依赖，没有创建根级 CMake 或 vcpkg manifest，没有生成或构建 LMCP／UxAS，没有启动 AMASE；未提交或推送。

## 2. 版本、来源与实际验证

| 项目 | 固定值 | 本轮结果 |
| --- | --- | --- |
| Build Tools 2022 | 17.14.41／17.14.37710.0 | bootstrapper 文件版本、SHA-256 与微软 Authenticode 签名有效；安装未执行 |
| MSVC | v143；目录声明工具包 14.44.35229 | 仅核查发布元数据；编译器、安装目录与 CRT 尚未验收 |
| Windows SDK | 发布 10.0.26100.7705；预期 kit 10.0.26100.0；包 Win11SDK_10.0.26100 为 10.0.26100.15 | 仅核查发布元数据；实际 SDK 未安装，三种版本含义不混用 |
| CMake | 3.31.12 Windows x86_64 | 压缩包与解压文件校验、版本命令通过 |
| Ninja | 1.13.2 Windows | 压缩包与程序校验、版本命令通过 |
| vcpkg checkout | `9e593bb18ea69cc5095e012465dcd675a822ed0d`（2026.07.29） | 完整历史、detached HEAD、受跟踪文件未修改；未构建端口 |
| vcpkg.exe | 2026-07-27，输出工具提交 `98d7cb0cf1f4686a3e43aa5672b6230c1d56bce8` | 二进制 SHA-256、checkout 的工具元数据及版本输出相符 |

来源：[微软固定发布](https://learn.microsoft.com/en-us/visualstudio/releases/2022/release-history)、[CMake 3.31.12](https://github.com/Kitware/CMake/releases/tag/v3.31.12)、[Ninja 1.13.2](https://github.com/ninja-build/ninja/releases/tag/v1.13.2)、[vcpkg 2026.07.29](https://github.com/microsoft/vcpkg/releases/tag/2026.07.29)。各便携下载校验值及校验来源均入工具清单；本机绝对路径只留在被忽略的原始记录中。

该 vcpkg checkout 的工具清单默认指向 CMake 4.4.0。项目入口在当前进程设置 `VCPKG_FORCE_SYSTEM_BINARIES=1`，移除冲突的强制下载变量，并将锁定的 CMake／Ninja 放在 PATH 前部。`vcpkg fetch cmake`、`vcpkg fetch ninja` 实际返回项目内对应程序，退出 0；入口独立校验其版本及文件，不依赖此强制模式进行版本约束。[官方环境变量说明](https://learn.microsoft.com/en-us/vcpkg/users/config-environment#vcpkg_force_system_binaries)

## 3. 阻塞：微软组件目录与官方校验值不一致

官方 release channel 在本轮返回 VisualStudio 17.14.37710.0 的组件目录记录，但固定地址实际返回的文件不匹配：

| 项目 | 官方 channel 声明 | 三种下载方式的实际结果 |
| --- | --- | --- |
| 字节数 | 30,443,537 | 17,954,732 |
| SHA-256 | `6e470016e4324c84c255ffd0beb3767d17ec89cc8561e9409ee3e1f6d29400f5` | `f0a50ea157222c29abd5ea6ff01bfc3c33b04e011c5e45ee2ca38ef0778e5643` |

下载方式分别为 PowerShell `Invoke-WebRequest`、curl 加查询参数避开缓存、PowerShell 显式请求 identity 编码并禁用缓存。三次内容一致，JSON 可解析且内部版本为 17.14.41；这些事实不能替代完整性校验。尚不能确定是源站／CDN 元数据还是传输链路导致，不认定为已确认的微软发布故障。

11:14 首次完整准备退出 1，在安装前被校验阻断；完成脚本实现后 11:25 再执行完整入口，仍得到同一不匹配结果并退出 1。没有将观察到的哈希直接改成信任值，没有忽略目录校验或换用浮动版本。

证据位于 `out/runs/g2-t01-setup-20260918-111401-925/`、`out/runs/g2-t01-setup-20260918-112530-241/` 和 `out/runs/g2-t01-source-check-20260918-112152-652/`；最后一项保存原始官方 channel、官方 payload 及本地文件实测哈希。失败下载保留在 `.tools/downloads/` 的独立 `.part`／诊断文件中，不充当合格缓存。

一次性来源诊断最初未正确处理 HTTP 二进制响应，导致 `official` 字段为空；原记录 `g2-t01-source-check-20260918-112200` 保留，随后改为保存原始响应文件再解析，以上 `112152-652` 记录按实际时间标明更正。目录名不作为执行时间依据。

## 4. 可复现入口与验收结果

以下命令工作目录为仓库根目录，均显式使用 PowerShell 5.1 的进程级执行策略。便携模式用于继续验证独立部分，**退出 0 不代表 T01 完成**。

```powershell
# 已实际通过：准备／复用便携工具。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-cpp.ps1 -PortableOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-cpp.ps1 -PortableOnly -VerifyOnly
# 已实际通过：便携工具及隔离故障验收。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\cpp-toolchain.tests.ps1 -PortableOnly
```

便携准备记录 `g2-t01-setup-20260918-111621-484` 为 `portable-ready`；增加真实 vcpkg 工具解析核查后的复用记录 `g2-t01-setup-20260918-111805-014` 亦退出 0。完整版本输出和工具解析命令在各批次 `command-*.json`。

九组便携验收：

1. 版本、哈希及 vcpkg 的 CMake／Ninja 实际解析。
2. 从其他工作目录重复准备，复用已验证工具。
3. 中文加空格的独立工具副本成功运行准备检查。
4. 损坏程序被拒绝，失败环境启用不改变父进程环境。
5. 缺失程序被拒绝。
6. 清单版本不符被拒绝。
7. 下载缓存损坏被拒绝。
8. vcpkg checkout 被修改时拒绝。
9. 完整进程环境恢复、用户／系统 PATH 不变，工具与输出被 Git 忽略。

首轮 `g2-t01-tests-20260918-112041-668` 退出 1：前八组通过，但恢复环境时把空的 `COLORTERM` 删除。原因是 .NET Framework 将空字符串视为删除变量。修复为仅恢复有变化的项，并用 Windows 原生接口保留“空值”和“不存在”的区别；小范围复查显示环境 68 项全部一致。`g2-t01-tests-20260918-112402-237` 九组通过、退出 0、状态 `portable-passed`。最终收尾复验 `g2-t01-tests-20260918-112530-237` 同样九组通过、退出 0，保存八个实现输入文件的 SHA-256；未验证项目在结果的 `notValidated` 数组中明确列出。

隔离故障只作用于 `out/tests/<run-id>/` 的副本；原工具的哈希、checkout 和既有 G1 输入未修改。没有为故障测试卸载系统组件。

交付文档检查 `g2-t01-docs-20260918-113340` 退出 0：16 个交付文件、194 处本地链接／锚点、41 个表格和 UTF-8／代码块检查通过；八个实现输入哈希与最终便携验收一致。四个 PowerShell 脚本语法解析及 `git diff --check` 通过，工作日志历史前缀、G0／G1 backlog 历史和暂存区保持不变。该静态检查不补足原生编译验收。

以下为恢复后的执行入口，**本轮尚未通过**：

```powershell
# 来源校验恢复后，才可能进入官方安装器的 UAC 提升流程。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-cpp.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\cpp-toolchain.tests.ps1
# 完整准备通过后，在新的交互进程启用；关闭该进程即结束启用。
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File .\scripts\windows\use-cpp.ps1
```

完整准备拟安装 C++ Build Tools 工作负载、v143 x86/x64 工具和指定 SDK，不使用 `--includeRecommended`；设置 `--norestart`，安装返回 3010／1641 时记录 `reboot-required`，不计通过。安装取消、失败、待重启分支目前只完成代码检查，尚无真实安装执行证据。编译验收将检查 VS／Ninja 的 Release x64、`/std:c++14`、`/MD`、PE 架构、运行输出、库搜索信息和中文空格路径；当前全部待执行，CRT 实际加载来源仍待核实。

## 5. 恢复条件与交接

保持当前锁定值。先取得与官方校验记录一致的目录文件，或取得可独立验证、明确对应固定版本的官方更正记录；不能只用本地下载结果更新信任值。没有新来源证据时不继续重复下载或安装。

恢复后重查工作区与系统，运行完整准备和完整探针套件。只有 MSVC／SDK／CRT 来源、两个生成器、不同工作目录和中文空格路径下真实编译／链接／运行全部通过，才登记 T01 完成、T02 可执行。系统安装需重启时保留记录，待用户完成 Windows 重启后再验收。

本轮已经验证的便携工具可以复用；原始失败记录保留。无需回退共享组件，因为安装器尚未启动。后续依赖兼容性、registry baseline、overlay ports 和 triplet 仍归 T02，不因 vcpkg 程序可运行而提前验收。

## 6. 来源阻塞修复及完整工具链验收

用户要求“解决阻塞原因，然后继续”后，保留前次全部工作区修改与失败证据继续 T01。

### 6.1 验证依据及修复

阻塞的直接原因是自建入口只把 channel 的描述摘要作为实际目录实体的校验依据，没有利用微软原生清单签名验证。进一步核查取得了可独立复现的新证据：

1. 已核验 SHA-256 和微软 Authenticode 签名的固定 17.14.41 bootstrapper 创建最小下载 layout，退出 0。它取得的 `Catalog.json` 与此前文件完全一致：17,954,732 字节、SHA-256 `f0a50e…e5643`；微软日志明确记录 `ManifestVerifier Result: Success`，并加载 `VisualStudio/17.14.41+37710.0.-september.2026-`。
2. 使用官方 `--layout <目录> --verify --wait --quiet --norestart` 复验同一缓存，退出 0，日志为 `Verification completed. No problem was found.`。诊断与复验记录在 `g2-t01-layout-diagnose-20260918-114403-618`。
3. 在隔离目录中仅将目录元数据的 `productPatchVersion` 从 41 改为 42；同一微软验证入口退出 `-2146233088`，明确记录摘要不匹配、`ManifestVerifier Result: InvalidSignature` 和该副本路径。负向证据为 `g2-t01-manifest-negative-20260918-114646-932`。正式目录和系统组件未被改动。

据此将**经过微软签名验证的实体哈希**锁定为 `catalog.sha256`，原 channel 声明完整保留在 `channelDeclaredSHA256`／`channelDeclaredSize`。不能推广成“遇到哈希不符就接受下载值”：此次更改依据是受信任的微软原生验证和篡改拒绝对照。channel 描述值为何与目录实体不同仍未确认；未认定网络损坏，也没有虚构微软发布了更正通知。

完整准备现在同时执行实体哈希检查、固定版本／组件检查、微软原生 layout 签名及全部缓存验证，然后从此缓存安装。layout 位于 `.tools/vs-buildtools-17.14.41/`，安装器 OPC 包 SHA-256 为 `b589a5f7874027a881b569466e12a4ef7d25cfe565e85465aa164220b7560453`，实际安装器版本为 4.10.30.62513；该包先由签名有效的 bootstrapper 验证，再纳入锁定与证据。未使用跳过签名、任意接受摘要或浮动产品版本选项。[微软 layout 参数](https://learn.microsoft.com/en-us/visualstudio/install/use-command-line-parameters-to-install-visual-studio?view=vs-2022#layout-command-and-command-line-parameters)

### 6.2 实际安装与脚本适配

`g2-t01-setup-20260918-114914-983` 的完整 layout 准备及验证均退出 0；其中安装器在 11:52:10～11:53:57 执行，退出 0。Build Tools 安装在微软系统默认目录；vswhere 显示版本 17.14.37710.0、`isComplete=true`、`isLaunchable=true`、`isRebootRequired=false`。未自动重启；用户与系统 PATH 前后相同。

实际启用阶段发现并修复两项原先无法动态验证的问题：

- 当前安装器的包列表位于 `state.packages.json`，`state.json` 保存实例及选择信息；原脚本读错字段，误报包版本缺失。改为读取独立清单并同时保存其哈希后，工具包 14.44.35229、SDK 包 10.0.26100.15 与签名目录一致。
- PowerShell 5.1 向 `cmd /c` 传递嵌套引号时，含空格的 VsDevCmd 路径被拆分。改用签名有效的 `Microsoft.VisualStudio.DevShell.dll` 和官方 `Enter-VsDevShell`，指定实例、Host／Target amd64、SDK 与 `SkipAutomaticLocation`；避免手工跨 Shell 编码和路径转义。

上述两次后置失败均保留：`g2-t01-setup-20260918-114914-983`（安装器成功，但总体因包清单读取失败而 failed）和 `g2-t01-setup-20260918-115452-665`（环境入口失败）。未将安装成功冒充完整工具准备通过，未因后置失败重复安装系统组件。

修复后 `setup-cpp.ps1 -VerifyOnly` 批次 `g2-t01-setup-20260918-115658-150` 退出 0、状态 passed。实测版本：

| 项目 | 实际值 |
| --- | --- |
| Build Tools | 17.14.41／17.14.37710.0 |
| MSVC 工具目录 | 14.44.35207 |
| cl.exe 文件版本 | 19.44.35229.0 |
| link.exe 文件版本 | 14.44.35229.0 |
| SDK include／lib 目录 | 10.0.26100.0 |
| SDK rc.exe 文件版本 | 10.0.26100.7705 |
| Host／Target | x64／x64 |

这说明工具目录名、包版本和程序文件版本并不总是相同，入口分别记录，不通过猜测目录名判断实际编译器。

### 6.3 完整验收结果与复用命令

完整验收 `g2-t01-tests-20260918-120323-636` 于 12:03:23～12:05:30 执行，退出 0、状态 `passed`。第 4 节的九组便携检查在完整工具环境下全部通过，并增加真实编译运行组，共十组。所有构建均使用本批次新建的输出目录，从临时工作目录调用，没有复用旧探针程序。

| 路径 | 生成器 | C／C++ 编译、链接、CTest 及直接运行 |
| --- | --- | --- |
| 仓库探针目录 | Visual Studio 17 2022 | Release x64／v143，两个程序均通过 |
| 仓库探针目录 | Ninja | Release x64／MSVC，两个程序均通过 |
| `out/tests/<run-id>/工具 chain/` 独立副本 | Visual Studio 17 2022 | 源码、便携工具及输出均含中文空格，两个程序均通过 |
| 同一中文空格副本 | Ninja | 同上，两个程序均通过 |

八个程序的 PE 均为 x64，退出 0。C 输出 `C_PROBE_OK x64 MD int64=9007199254740993`，C++ 输出 `CPP_PROBE_OK x64 MD c++14 int64=9007199254740993 threads=2000`。编译期检查 C++14、动态 CRT 和 Release；源码保持 C++11 兼容。编译／链接原始日志保存实际命令、`/Bv`、头文件和库搜索输出；结果包含程序哈希、PE 依赖、系统工具清单与输入哈希。

首次完整探针批次 `g2-t01-tests-20260918-115746-651` 退出 1：普通路径的两个生成器已经编译运行成功，但检查器仅接受 `/std:c++14`，误判 Ninja 实际输出的 `-std:c++14`。将检查改为同时接受 `/` 和 `-` 前缀后，上述最终批次全部通过；未改动探针语义或降低标准要求，原失败证据保留。

四个 C++ 程序另以 `--inspect-runtime` 正常运行并退出，验收读取本次进程实际加载的模块，确认位于 Windows 系统目录：

| 实际加载模块 | 文件版本 |
| --- | --- |
| `MSVCP140.dll`、`VCRUNTIME140.dll`、`VCRUNTIME140_1.dll` | 14.50.35719.0 |
| `ucrtbase.dll` | 10.0.26100.9444 |

安装清单的 VC Redist 包为 14.44.35211；本机运行时使用已有的较新系统 DLL。**安装包、构建工具／链接库和实际运行库分别记录**，不将系统 DLL 写成编译器版本，也未为版本一致而降级共享运行库。模块路径、SHA-256 与完整文件版本只保存在原始证据中；未测试部署到其他机器。

完整准备复用 `g2-t01-setup-20260918-120408-848` 退出 0，复用既有工具，无重复系统安装。独立环境入口检查 `g2-t01-activate-20260918-120449-605` 从临时工作目录实际调用 `use-cpp.ps1`，确认 Host／Target x64 和固定工具解析，随后恢复全部进程环境，退出 0。用户／系统 PATH 无持久修改，未执行全局 vcpkg 集成或安装端口。

以下命令现已实际验证，工作目录为仓库根目录；入口自身也支持从其他工作目录以绝对脚本路径调用：

```powershell
# 准备或校验并复用固定工具；首次安装仅微软安装器请求 UAC。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-cpp.ps1
# 只检查已有工具，不安装或下载。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-cpp.ps1 -VerifyOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\cpp-toolchain.tests.ps1
# 新交互进程中启用；关闭进程即结束本次环境。
powershell.exe -NoProfile -ExecutionPolicy Bypass -NoExit -File .\scripts\windows\use-cpp.ps1
```

准备／验收入口退出前恢复其修改的进程环境。后续构建脚本应在自己的进程内启用并恢复工具，不依赖已经退出的子进程修改父终端。便携模式仍保留，但不代替完整验收。

### 6.4 交接与限制

T01 已达到来源锁定和真实 x64 C/C++ 最小闭环的完成条件，T02 可执行、尚未启动。没有创建根级 UxAS CMake、业务依赖 manifest／overlay／triplet，没有编译 LMCP 或 UxAS，也没有运行 HelloWorld 或 AMASE。后续按 T02 构建依赖，再推进 T03～T07；T01 通过不等于 G2 阶段完成。

故障注入仅作用于隔离副本；安装签名篡改拒绝、工具损坏／缺失、版本不符和 checkout 变化已实测。安装取消、一般安装失败和待重启分支保留状态与诊断处理，但本机真实安装退出 0，未通过刻意中断或破坏共享组件制造这些状态。channel 描述哈希差异的发布端原因仍未知，其实体真实性已由固定微软签名验证链及负向对照验证。

保留全部历史失败、layout、安装和验收记录；后续失败不会覆盖已有合格记录，不自动卸载 MSVC／SDK。项目文档与忽略规则的最终检查见工作日志 WL-20260918-004。本轮不提交或推送。
