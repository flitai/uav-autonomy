# G4 → G5 接口与运行交接

G4 已完成并发布。T08 两模式各 30 分钟、T09 原两实体两模式、本轮真实 GUI 确认及同版本完整 20 实体受控复验、正常退出和独立审计均通过。实际证据见 [T09 报告](g4-stage-validation.md)。

## 运行入口

工作目录可独立于仓库，PowerShell 参数采用完整路径。先用实际 Python 3.14.7 x64 解释器运行；入口自行复查项目独立环境、生成模型和正式后端。以下日常入口已从中文空格工作目录实际消费正式包，验证两种场景及网关自动恢复。示例以仓库根目录为工作目录；在其他目录运行时把脚本路径改为绝对路径。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\start-g4-session.ps1 -PythonExecutable $pythonExe -Scene Mixed20 -Mode Gui
```

`Scene` 可为 Original／Mixed20，`Mode` 可为 Gui／Headless。输出 `G4_SESSION_RUN_ID`，数据和进程身份记录在该运行的 `out/runs/<run-id>/`。运行以真实 1 倍推进；原两实体完成或 20 实体到 785 仿真秒后暂停，保留诊断接口和后端，供 G5 集成核查。会话使用独立编排，浏览器关闭不结束后端。正常结束由运维在该运行根目录创建空 `request-stop` 文件；控制器将关闭自己的网关和后端并检查端口释放。此为开发运行入口，浏览器控制与重置继续归 G6。

网关独立重启入口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g4-gateway.ps1 -PythonExecutable $pythonExe -Manifest '<本次 manifest.json>' -ManifestSHA256 '<该清单 SHA256>' -OutputDirectory '<新的实例输出目录>'
```

日常 start-g4-session.ps1 自动管理网关：在当前 observer 目录创建 request-stop，旧网关正常退出后自动启动新实例，后端继续推进。需要暂留离线时先创建根运行目录 gateway-offline，移除此文件后自动恢复。上面的独立网关命令供独立编排使用，不能与日常自动管理会话争用同一端口。清单必须绑定仍在运行的本次后端、原 UxAS 消息日志和同一持久事件库。停止旧网关时在其 observer 输出目录创建空 `request-stop`，正常退出后再启动新实例；不能复用旧输出目录。该入口只读旁路，不发送任务，不负责启动／停止后端。最终验收控制器主动管理网关，不应在验收中手动替换它。后端退出或主链路变化必须整组新建运行，不能用此入口续接旧任务。

## G5 消费约定

服务地址 `http://127.0.0.1:8000/`；诊断页面不依赖外网资源。接口和全部字段定义见 [浏览器协议 v1](g4-browser-contract.md)。

当前诊断页与 API 同源。G5 的页面应采用同源接口路径或配置开发代理；当前网关没有开放通用跨域 HTTP。正式网络部署和访问控制不由本机 G4 验收替代。

| 接口 | G5 的处理 |
| --- | --- |
| GET /api/v1/health | 检查 ready、status、run_id、stream_id、连接与恢复状态；HTTP 200 不等于数据就绪 |
| GET /api/v1/snapshot | 诊断查询；未就绪为 503。不能把此查询与另一个 WS 的增量拼接 |
| WS /api/v1/stream | 同一连接首个业务包为 snapshot，随后逐序 delta；可能先收到 health 后 1013 关闭 |

客户端每次连接清空旧流，等待快照；之后校验运行／流身份和严格连续序号。序号与 int64 标识、仿真时间均为十进制字符串，JavaScript 比较用 BigInt。收到新流、断线、503、1013 或序号缺口时重新连接并获取快照。不得继续沿用旧插值轨迹、旧任务缓存或外推后端时钟。浏览器 WebSocket 只接收；业务输入将被 1008 关闭。

delta 的 `changes` 为显式集合 upsert／delete；upsert 替换该键的完整对象。simulation 更新单独替换时钟对象。TaskComplete 保留任务，删除和过期各有独立语义；命令 received、execution_observed 和任务 backend_completed 分别呈现。

TaskComplete 不停止实体的终端飞行行为。独立分析报告按本次采样窗口统计，点搜索观察秒数与线／区域覆盖不能直接解释成“任务完成瞬间”的值；网关快照中的完成时间保留后端原值。

AMASE 是实体位置、姿态、仿真时钟的权威来源；UxAS 提供规划及任务事件。所有位置保留经纬度、米制高度和原高度基准；姿态保留源值。G5 再校核 Cesium 坐标、轴向和高度转换。G4 历史测试使用零高程；后续 G5-T04 已独立验证真实地形后端，T05 已使用其合格场景接入，Cesium 实体坐标／姿态校准仍归 T06。

## 恢复和性能边界

观察链路或网关恢复采用本次已提交 UxAS 消息日志重建，再发布新快照；只宣称语义补齐。原始 TCP 缺失字节和残包保持缺口记录。异常日志、旧运行、后端退出或主链路改变均拒绝 live。

T08 本机 20 实体每架源更新约 1.88 Hz，普通客户端 P95 延迟约 218～227 ms；慢客户端通过关闭和新快照同步，最终状态一致。30 分钟测试中网关私有内存峰值约 73.3 MiB、队列每客户端上限 256 条／8 MiB；每模式记录约 2.47 GB。900 秒时整网关重启恢复约 48～54 秒，期间应明确显示恢复中。以上实测机器、方法及完整分位数见 [T08 报告](g4-scale-validation.md)，不作为普遍性能承诺，也没有 250 ms 硬门槛。

## 来源与后续边界

候选／正式网关保持 T08 相同业务代码；包清单绑定全部代码、工作区生成模型及独立环境，实际启动记录导入路径和摘要。正式指针为 `out/artifacts/gis-gateway/current.json`，本轮发布编号 g4-t09-publish-20260920-115418-723744；包清单摘要 `dcc6b6294ff0687ae690f6518780b2ba563339b177ba7c79b22b3aa9ff41689e`，资格摘要 `245d2fdc1d5699784c088f8f0e762365009e892e2aa19fbf413b45f66db39c51`。日常入口资格 `out/artifacts/gis-gateway/session.json` 绑定 g4-t09-release-check-20260920-115528-388842 和当前正式指针，入口或包变更须重验。开发工作区的 qualified 后端／生成代码／环境仍是消费前提，第二机器部署归 G8。

G5 已按用户确认的 [实施方案](g5-cesium-display-plan.md) 细化为 [十一张任务卡](backlog.md#9-g5-顺序与任务卡)，T01 环境及最小工程已完成，见 [环境报告](g5-environment-validation.md)；T02 已完成 USGS 区域同源地形资格，见 [地理检查报告](g5-geography-validation.md)；T03 地图与本地资源服务、两类路径及生产／开发、断网／在线矩阵通过，见 [地图报告](g5-map-validation.md)；T04 两模式三实体真实地形任务及独立统计已通过，见 [后端地形报告](g5-backend-terrain-validation.md)。T05 两模式真实首次／晚加入／刷新、状态重放与暂停快照对照已通过，见 [状态报告](g5-state-validation.md)；T06 模型／姿态／时间显示已通过，T07 航线／任务／区域图层可执行。G5 新增本地矢量／DEM、在线卫星影像及 Cesium／AMASE 同源真实地形；后端零高程基线保持历史资格。T04 原平面几何和任务身份保留，共同地形赋高、统一 +390 米飞行高度适配已冻结，不属于覆盖效果寻优；当前非负区域的实际路径避开旧 DTED 间距字段缺陷，负值继续拒绝，相机四角仍为局部平面近似。后续真实链路须绑定本卡场景／地形和正式后端，原两实体／20 实体完整显示联调归 T09／T10。交互控制和重置归 G6，正式历史回放归 G7，第二机器与离线影像包归 G8；算法／覆盖效果优化以及任意 Unicode 业务字符串兼容不在 G5 范围。

G5 当前日常联合入口为 `scripts/windows/start-g5-entities-session.ps1 -PythonExecutable <已核查解释器> -BuildRunId <T06 候选编号> -Mode Gui`，使用合格三实体地形场景与正式 G4；生产页面 8080，网关 8000。它独立于上述 G4 零高程入口，原入口和历史资格保留。完整命令、运行边界和候选编号见 [T06 报告](g5-entities-validation.md)；T05 原状态入口保留。

G5-T06 已完成真实模型／姿态／时间显示，选择／轨迹／定位／跟随／复位及 +／-／0 模型倍率操作通过。UCAV 来源由用户说明为 AFSIM，1 源单位＝1 显示米；高度按 EGM96 改正一次，消息与后端性能不变。两模式短程显示、离线地图和正常退出不替代 T09／T10 全程，下一卡为 T07，正式前端发布仍归 T11。

T06 当前候选已增加 [荧光阵营色／描边](g5-affiliation-display-validation.md)。直接读取 entities[id].configuration.Affiliation；仅当后端 Unknown／缺失时补充用户显示指定，保留原快照与来源，未增加 G4 字段或控制接口。

T06 后续显示修正已通过 [固定屏幕尺寸与立体光照验收](g5-model-display-validation.md)：动态屏幕缩放、展示补光只作用于模型；原 G4 v1、坐标／姿态／时间和后端性能保持，显示模型尺度不能当作真实机体占地。

T06 当前 [逐帧平滑移动修正](g5-motion-validation.md) 保持 G4 v1 和后端时间；本地时间只用于已收数据缓冲的播放，不允许外推。真实浏览器静止／跟随视角的消息间移动通过，暂停及旧流清理规则保持。

T06 新外观供用户预览：[银灰金属主体与阵营细描边](g5-metal-display-preview.md)，普通 1 像素、选中 1.5 像素；G4 阵营原值、消息和业务时间保持，位置／姿态仍按已收样本逐帧显示。

T06 当前消费候选见 [近景跟随修正](g5-close-motion-validation.md)：跟随相机和模型尺寸与已收样本插值同帧计算，动态轨迹避免阻塞；384 px／近景／旋转真实两模式通过。G4 协议、时间、正式包保持，未增加控制接口。
