# G3-T02：真实双向协议与来源验证

日期：2026-09-19，Asia/Shanghai。**G3-T02 已完成。** 候选及正式产物的六组协议验收通过；本轮 GUI 人工确认、正常退出、AMASE／UxAS 复验发布及当前输入资格完成。最终正式协议收据为 `g3-t02-verify-20260919-104721-817`，下一项 T03 可执行、尚未启动。

本卡不启动自主搜索规划。两实体的配置和动态状态来自实际 AMASE；测试命令 97001／97002 由真实 UxAS 的 SendMessagesService 从隔离 XML 加载并发送，内容派生自原巡航命令。原任务 1000 用于核查真实 C++ XML 读取及 Java 接收。没有 AutomationRequest、任务分配或完成／覆盖率声明。G3 保持“系统闭环及覆盖统计正确”，不设覆盖率门槛。

## 1. 输入、修复与来源

开始时工作区干净，Git 为 `a1c814bf257b8854a6897a83ef629e8a51b094a2`。正式基线重查 `g3-t01-check-20260919-095541-064` 通过，使用当前 acceptanceRevision=2；模型、生成器和同批七模型生成代码均未改动。原示例 XML 保留。

| 真实复现 | 现象 | 本卡修复 |
| --- | --- | --- |
| Java 接收分包标记 | 原接收器一次 read 读取 7 字节；在标记中分包后，C++ 已发送的 97001／97002 均未进入 AMASE 事件总线 | [SentinelMessageReader](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/SentinelMessageReader.java) 在 TCP 边界逐段读满，校验外层／属性／LMCP；[TcpServer](../OpenAMASE/OpenAMASE/src/Amase/avtas/amase/network/TcpServer.java) 改用该读取器，发送按连接串行化 |
| 正常停止阻塞 | UxAS 收到 KillService 后，空闲 TCP 接收线程无法退出，超过 30 秒只得清理本次进程 | 内部 PULL 接收与代理 poll 使用 100 ms 有界等待；拒绝空消息后再读属性；代理先停止线程再销毁成员；STREAM socket 由基类关闭，不向自身路由 ID 发送断开包 |
| 原巡航命令回送 | 两条 AMASE 原始命令 100 进入 UxAS 后又各回送一次；没有无限循环，但造成不必要的重复命令事件 | TCP 桥增加默认关闭的 `ExportOnlyLocalMessages`，主链路显式开启；仅导出本地 EntityID 且非该桥自行导入的消息。观察桥保持完整订阅 |

未修改 LMCP 工厂、模板或生成输出。Java 新读取器规定外层 body 上限 1 MiB、属性上限 4096 字节；严格核对声明长度、两层实际校验和、根标记、解码长度与类型描述，校验和 0 不作为通配值。坏帧或残包 EOF 关闭该 Java 连接，其他连接继续工作。

UxAS 本卡修复生命周期和导出方向；没有把原生 C++ 接收器改造为完整不可信网络防护层。严格验收器拒绝坏帧与原生后端的实际拒绝行为分别记录，不能以生成工厂可解码代替校验。

## 2. 真实拓扑与来源矩阵

协议试验使用无界面 AMASE 5556、实体 19400／19500、UxAS 观察 9999、PUB／PULL 5560／5561。分包试验另在 5557 使用按原字节转发的捕获器；它只控制传输分块，不翻译协议或生成后端状态。原始双向流、实际发送分块、解码消息与 AMASE 内部事件分别保存。直接连接试验把 UxAS 直接连接 5556，额外 AMASE 客户端及 UxAS 观察客户端只采集；以 PID、建立连接和内部事件核对实际链路。

| 输入／出口 | 保留来源（正式方向） | 改写来源（对照） |
| --- | --- | --- |
| Java 实际状态封装 | EntityID=0、ServiceID=0；业务实体为 400／500 | Java 原始帧仍为 0／0 |
| UxAS 主 TCP 导入 | `ConsiderSelfGenerated=false`，总线保留 0／0 | true，总线改写为 EntityID=100、该桥 ServiceID，Group=TcpBridge |
| UxAS TCP 观察口 | 收到两实体真实动态状态，保留属性 | 收到相同实际载荷及改写属性 |
| UxAS PUB | 排除来源 0 的状态；本地 HelloWorld KeyValuePair 是订阅有效的正向对照 | 导出来源已改为 100 的状态 |
| UxAS 主 TCP 导出 | 订阅 MissionCommand、LineSearchTask、VehicleActionCommand，开启 `ExportOnlyLocalMessages=true` | 同样开启；过滤本桥导入后改写的消息 |
| 观察客户端注入 | 只发送测试消息及 KillService；不回送收到的业务消息 | 同左 |

完整状态必须通过 TCP 观察口读取；不能把 PUB 看不到状态解释为 AMASE 没有发送。来源 EntityID 与载荷内实体 ID 分开使用。本方案是本机指定链路的来源核对，不提供身份认证。

## 3. 入口、证据与验收

独立入口为 [g3-protocol.tests.ps1](../tests/windows/g3-protocol.tests.ps1)，编排在 [scripts/g3_protocol](../scripts/g3_protocol/run.py)，Java 事件探针、原生 ZeroMQ SUB 和反例在 [tests/g3_protocol](../tests/g3_protocol/ProtocolProbe.java)。编排使用已核查的 Python 3.14.7 x64 和固定 Java／C++ 工具，恢复进程环境、工作目录、编码，检查持久 PATH 未变。

候选模式必须同时提供 AMASE 构建、UxAS 构建与候选验收编号，通过原有解析器核对实时源码、包与收据；原 T01 冻结输入只允许已登记的通信修复差异，保存修复前后摘要。缺一个候选编号、其他来源变化或无效收据均失败，不绕过正式来源校验。

```powershell
# 仓库根目录；也支持从其他工作目录用脚本绝对路径调用。
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g3-protocol.tests.ps1 -PythonExecutable $pythonExe -BaselineRunId g3-t01-check-20260919-104119-819
```

原程序的缺陷复现为 `g3-t02-reproduce-20260919-101142-414`：正常传输能收到两个测试命令，分包时零个；两组均记录真实 UxAS 关闭超时和强制清理，不能算闭环通过。早期端口过早检查、原命令与测试命令混计及候选修复清单漏列头文件的失败均保留；修正验收编排后重新运行，没有更改旧失败收据。

修复后首轮候选协议验收 `g3-t02-verify-20260919-102134-514` 通过：保留来源、改写来源、分包、受控断线、整组新建共五组；受控断线子运行保持 failed 并由 expectedFailureVerified 表示预期故障被正确处理。各业务进程退出 0、无强制终止，全部所属端口释放。Java 生产读取器检查 150 个分包位置、151 个截断位置、双帧粘包及 20 个派生坏帧通过；Python 严格解析器对真实 Java／C++ 样本分别覆盖所有拆分点、粘包、EOF 和十类畸形输入。

补充直连及原任务 XML 载荷的 `g3-t02-verify-20260919-102501-138` 六组通过。人工复核原始 XML 后发现探针误用 ViewAngle 子节点名，已改为实际 Wedge 并增加有效值断言；保留旧收据，不能把旧收据的空列表当作后端字段值。最后从仓库外系统临时目录运行 `g3-t02-verify-20260919-102900-997`，六组、生产 Java 读取器及严格解析反例全部通过，result／entry-result 均 passed，四项环境恢复检查通过。此批次还核对真实配置进入 UxAS、两实体至少十条时间增长且位置变化的状态、逐帧无重复、实际类加载来源、全新 PID，以及每个子运行证据文件的哈希。

| 最终候选子运行 | Java 状态条数 | UxAS 观察状态条数 | PUB 状态条数 | 结果 |
| --- | --- | --- | --- | --- |
| preserved-source | 43 | 43 | 0 | 通过 |
| rewritten-source | 41 | 41 | 41 | 通过 |
| fragmented | 41 | 41 | 0 | 通过 |
| disconnect-partial | 41 | 41 | 0 | 按预期失败，整组正常关闭 |
| fresh-group-after-disconnect | 41 | 41 | 0 | 新进程／新解析器通过 |
| direct-connection | 45 | 43 | 0 | 直接 TCP 连接通过 |

直接连接的 AMASE 被动观察客户端较早接入，比 UxAS 观察流多见两条状态；所有进入 UxAS 的状态都能在真实 Java 流中找到对应载荷，未用静态状态补齐。该时序差异不替代 T03 初始数据屏障的验收。最终严格 Python 检查分别覆盖 Java 帧的 151、C++ 帧的 342 个拆分／截断位置，每个方向十类畸形反例；Java 生产读取器结果仍为 `split=150 eof=151 coalesced=2 malformed=20`。

实际字段核对：两实体 CameraConfiguration 的当前单值 SupportedWavelengthBand 均为 EO；原任务重复 ViewAngleList 经真实 C++ 读取后，最终为一个 Wedge，AzimuthCenterline=35、VerticalCenterline=-60、两个 Extent=0；DesiredWavelengthBands 仍为 AllAny。上述值来自实际 AMASE 接收事件及两端载荷，不是按旧 XML 字面推断。未改原字段、视角或波段，统计语义留给 T05。

| 验收层 | 证据与实际判断 |
| --- | --- |
| 两层协议 | 双向原始字节、帧范围、封装和 LMCP 哈希；逐帧严格解码，半帧尾部另存 |
| Java 真实坏帧 | 连发两个合法 KeyValuePair 后发坏外层校验和：两条事件恰好收到，坏帧无事件且连接关闭；断开半帧后，新连接正常接收 |
| C++ 真实坏帧 | 坏外层长度与校验和未成为总线消息，后续粘连的两个合法消息各收到一次；内部 LMCP 坏帧仅由严格验收器反例保证拒绝，不宣称所有 C++ 后端都拒绝 |
| 来源与去重 | 状态载荷哈希与 Java 实际输出对照；保留／改写及 PUB 正向控制；测试命令 97001／97002 各一次，原命令 100 不回送 |
| 断线与残包 | 注入半帧后切断主链路，记录断线与失败，丢弃本轮解析器并正常关闭整组；后续用新进程和新解析器开始，不沿用旧运行 |
| 正常关闭 | 通过观察口发送真实 KillService(-1)，插件请求 AMASE 正常退出，SUB 正常关闭；30 秒超时只算失败并清理持有的进程 |

原始证据均位于 `out/runs/<run-id>/`，包含 result／entry-result、每个 case-result、PID／退出码、输入哈希、复制配置、三路 TCP／PUB 字节、分块记录、内部事件、日志及反例。仿真毫秒与墙钟独立保存，int64 ID 使用字符串。原始运行物不提交 Git。

## 4. 重建、发布与交接

| 项目 | 本轮身份与状态 |
| --- | --- |
| AMASE 构建 | `g1-t04-build-20260919-101509-695450`，通过 |
| AMASE GUI | `g1-t04-run-20260919-101533-522836`，本轮用户确认“GUI确认并正常退出”，自动检查和退出 0 通过 |
| AMASE 自动矩阵 | `g1-t04-automatic-20260919-101706-907868`，11 项通过 |
| UxAS 构建 | `g2-t05-build-20260919-101514-494`，通过 |
| UxAS 候选验收 | `g2-t05-test-20260919-101831-478`，普通／中文路径编译、平台／来源反例通过 |
| HelloWorld | `g2-t06-test-20260919-102042-847`，双向消息、正常退出及故障矩阵通过 |
| AMASE 发布 | `g1-t04-finalize-20260919-103730-933619`，人工确认、正常退出和发布通过 |
| UxAS 复验／发布 | `g2-t07-test-20260919-103739-909`／`g2-t07-publish-20260919-104007-031`，通过 |
| 当前输入资格 | `g3-t01-check-20260919-104119-819`，43 项冻结来源通过 |
| 正式协议复验 | `g3-t02-verify-20260919-104721-817`，六组与严格解析通过 |

根 CMake、依赖、MDM、生成器及生成输出未变，C++ LMCP 继续使用 `g2-t03-build-20260918-195001-565`／`g2-t03-test-20260918-195057-347`。旧包和历史验收报告保留；不能用新源码继续消费旧二进制并声称来源一致。

本轮候选 AMASE JAR SHA-256 为 `AD32BF2A2A084CF24C69CF644B8DA807B6045E7CEC11928FC0AB59419BCECAC9`，UxAS EXE 为 `036EA32D168859B089969F4EA24431BB52F9302B65C1EC185EA0A82D77CFA366`；最终协议收据绑定这两个产物及同批 Java LMCP 的哈希。AMASE GUI 在约 20 秒达到观察点，后于 10:35:56 正常退出，末条仿真时间约 380.76 秒，退出码 0、端口释放且自动结果通过。运行编号见表；随后用户明确回复“GUI确认并正常退出”，已通过既有 Finalize 发布；未复用 G1 历史确认或仅凭窗口关闭代替确认。

当前来源修订为 config/g3-baseline.json 的 inputRevision=2：原 35 项中三个通信源摘要更新，另把八个修复相关输入纳入冻结，共 43 项；before=null 表示原清单未登记，不表示文件原先不存在。修订保留原哈希、父收据及重建／验收依据；原 T01 报告和收据未改。acceptanceRevision 仍为 2，完整水道、20 米栅格及不设覆盖率门槛保持，十项输入反例复验通过。

正式首轮 `g3-t02-verify-20260919-104244-282` 的前五组通过，直连组因为观察连接建立较晚，漏记两实体初始配置而失败，所有进程正常关闭。没有删除配置完整性断言或静态补齐；在独立测试配置中移除 ConstructiveControl 自动启动，由协议探针等待主链路、观察连接及真实本地 KeyValuePair 就绪后，收到 request-start 文件才开始 1 倍速仿真。该屏障只保证 T02 取样，不实现 T03 的任务／请求屏障；未修改正式 AMASE／UxAS 二进制，GUI 确认仍适用于同一构建。

最终正式入口从仓库外使用已发布产物运行，明确检查隔离 Python 3.14.7 x64；六组及严格解析通过。每组的原始字节、配置、内部事件、PID／退出和证据摘要独立保存，受控断线子运行保持 failed 并验证预期处理，所有子进程正常关闭。

| 正式子运行 | Java／观察／PUB 状态条数 | 结果 |
| --- | --- | --- |
| preserved-source | 43／43／0 | 通过 |
| rewritten-source | 43／43／43 | 通过 |
| fragmented | 41／41／0 | 通过 |
| disconnect-partial | 41／41／0 | 预期断线失败已验证，正常关闭 |
| fresh-group-after-disconnect | 41／41／0 | 通过 |
| direct-connection | 39／39／0 | 通过 |

T03 将建立暂停启动、真实初始配置／动态状态屏障和单次任务请求；本卡的短时协议测试及 SendMessagesService 测试命令不能替代该工作。T04 验证自主规划命令实际执行，T05 验证完成和覆盖统计。C++ 同一进程在线重连、多个输入连接的残包隔离和完整恢复矩阵仍归 G4；本卡采用断线后整组停止重启，不承诺在线恢复。
