# G5-T03 地图与本地资源服务验收

日期：2026-09-20，Asia/Shanghai。**G5-T03 已完成。** 普通／中文空格路径各一份干净候选及各十组正式验收通过，日常启动入口另经新后端资格、实际 Edge 和正常退出验证。下一卡为 G5-T04。

## 1. 交付与边界

前端加载用户原始 `tiles/tiles/planet.pmtiles`，工作线程按 PMTiles v3 索引读取压缩 MVT，再绘制为 Cesium 影像瓦片。底图默认本地化；保留水系、道路、土地、建筑和地名等绘制，中文名称优先选择 `name:zh-Hans`／`name:zh`，没有中文时保留原名。范围仅为可浏览底图，底图要素不会成为仿真实体或任务。

USGS 真实地形消费 [T02 合格批次](g5-geography-validation.md) 的 `cesium-heightfield.f32`，从同一标准化网格派生。地形用 WGS84 椭球高，直接插值，不重复叠加正高或大地水准面改正。主源范围为西经 122～120 度、北纬 45～46 度，区域外明确使用未通过仿真资格的参考椭球，不使用旧 Terrarium 异常数据或 Copernicus 补洞。真实区域裁切边缘不向外延拓，不把区域边缘的截断当作全球真实地形接缝资格。

页面提供底图切换、区域地形与资格边界开关，以及验收区域、地形近景、全球和北京定位。资格边界是范围提示，暂以高于本区域地形的轮廓绘制；实体定位／跟随、任务区域和业务图层留待后续。后端时间显示未连接，T03 不取得真实仿真业务接入资格。

新增 `scripts/g5_map/` 和 Windows 独立入口，保留 T01 工具／样片历史入口与 T02 收据。生产包只使用本地静态资源服务，不运行 Vite；开发模式将 Vite 作为同一资源服务的中间件。正式前端指针未切换，人工确认与阶段发布归 T11。

## 2. 来源和运行契约

- 区域准备：`g5-t02-prepare-20260920-174145-970`，manifest SHA-256 `f0f6372b16cda86811750f83df44560ec345097fbcd695ad6fb6dffa7854a8c0`。
- 区域验收：`g5-t02-test-20260920-174558-688`，acceptance SHA-256 `3294d503ef172afd3f123a0a67a6393ef3b535f2eda1247b2fd6bdb57ff22c9a`。复核准备／工作／入口结果、输入和派生文件、当前工具与后端绑定。
- 主矢量：137,370,745,450 字节，SHA-256 `b4c4674234ae75c8fea8a10c23f1cce49626155f56a437eda89b006f1e02b2b7`。T03 构建重新计算全量摘要；启动检查文件大小、修改时间与头部，不将该启动检查称作再次全量哈希。服务期间原文件身份改变即拒绝请求。
- Node 24.21.0、TypeScript 7.0.2、Vite 8.3.0、Cesium 1.145.0 及 npm 锁沿用 T01；没有增加 npm 依赖。Cesium 四类资源本地复制。
- Noto CJK 简体中文字体与 OFL 许可来自固定官方提交 `f8d157532fbfaeda587e826d4cd5b21a49186f7c`，摘要见 [地图配置](../config/g5-map.json)。缓存位于 `.tools/cache/g5/map-assets/`，字体和许可进入候选；原模型的后续安排见 [模型登记](g5-model-inputs.md)。

| 接口／资源 | 当前契约 |
| --- | --- |
| 页面 | 生产 `127.0.0.1:8080`，开发 `127.0.0.1:5173`；冲突失败，不静默换端口 |
| `/map/runtime.json` | 地理版本、区域、高度基准、在线服务和限制；不暴露本机数据路径 |
| `/map/planet.pmtiles` | HEAD 返回大小、ETag、Accept-Ranges；GET 必须为单段 Range，最多 4 MiB；支持后缀／尾段，错误范围 416、If-Range 不符 412，不传整包 |
| `/map/terrain/{z}/{x}/{y}.f32` | GeographicTilingScheme，z0～14，65×65、北到南／西到东、float32 小端；响应注明合格节点数及区域外参考椭球语义 |
| `/api/v1/health`、`/api/v1/snapshot` | 原路径和查询参数代理至回环 8000，保留状态及 JSON 正文；后端不可用时返回 503 |
| `/api/v1/stream` | WebSocket 升级及双向传输代理，保留字符串整数、消息和关闭码；不增加业务控制接口 |
| `/map/health` | 地图服务就绪与有界请求计数，独立于后端 ready |

工作线程的压缩 Range 缓存最多 16 MiB／128 项，解码目录缓存最多 16 MiB／64 项；并发任务最多 4，单个解压结果最多 16 MiB，MVT 单次最多 20 万要素／100 万顶点，标签最多 100。超限明确拒绝。影像采用 512×512 瓦片、最高 z15；ImageBitmap 在工作线程中按 Cesium 的纹理约定翻转一次，页面不解码 MVT。

地形服务器保存一份约 11.5 MB 的合格高度场，瓦片缓存最多 64 片／1,081,600 字节；前端地形请求最多 8 个，Cesium 地球未用瓦片缓存目标为 128。请求日志只保留最近 128 条，服务同时处理最多 64 个 HTTP 请求，WebSocket 数量设上限。资源缓存与待处理队列有明确上限；Cesium 可见瓦片另随视锥及细分层级管理，不把缓存目标写成所有可见 GPU 对象的硬数量限制。

Esri 只在用户选择后加载，使用服务元数据和对应视图的来源标注；初始化超时或瓦片失败时恢复本地底图并提示。没有在线影像离线包，也不把一次在线成功承诺为永久可用。[ArcGIS 影像接口](https://cesium.com/learn/cesiumjs/ref-doc/ArcGisMapServerImageryProvider.html)

## 3. 验证方法与开发发现

正式验收由 `tests/g5_map/` 独立编排：Python T02 读取器产生真实 MVT 基准，TypeScript 编译后的解析器对照要素／顶点；地形参考使用 NumPy 独立重心坐标求解，分块边界逐节点比较；HTTP Range 字节与原文件直接对照。代理采用明确标注的本地协议夹具，覆盖超大整数、HTTP 503 和 WS 1013；这不是 T05 真实 G4 消息接入。

Windows Edge 使用独立目录和 CDP 检查实际页面。断网场景阻断外部 DNS，在线场景另开浏览器访问真实 Esri 服务；覆盖中文地名、地形近景、开关、定位、刷新、影像失败回退、资源缺失和正常关闭。截图保存实际地理显示，不替代业务联调。正式运行与检查进程使用独立 `out/runs`，冲突测试不终止已有实例。

开发阶段保留以下原始失败和修复过程：

1. `g5-t03-development-build-01`：Cesium 的类型声明要求瓦片丢弃策略等字段，已提供明确的 NeverTileDiscardPolicy 和只读接口实现。
2. `g5-t03-development-browser-01`：Edge 相对 profile 路径导致退出 21，探针改用绝对路径；后续均独立正常退出。
3. 首次实际截图显示 ImageBitmap 上下翻转，已在工作线程按纹理加载约定处理。修复后的北京地名与方位截图可核查。
4. `g5-t03-development-browser-03`：刷新时探针读取旧 Viewer 的已销毁属性失败，且截图失败阻断其 Browser.close，发生强制收尾；已清除旧检查句柄、识别销毁状态，并独立保证 Browser.close 执行。失败不计通过；`development-browser-04` 及独立在线轮次均通过并正常退出。
5. 独立测试最初误用了 TypeScript 旧 JS 编译 API，当前锁定版本为原生 TypeScript 7，已改用实际 CLI 编译测试对象。没有升级或替换工具锁。

正式结果见第 5 节。真实地形飞行、传感器和 20 米统计属于下一卡 T04；控制／重置仍归 G6。

## 4. 标准入口

在仓库根目录使用已核查的 Python 3.14.7 x64；入口也支持从其他工作目录调用完整脚本路径。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-g5-map.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g5-map.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<本次构建编号>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g5-map.ps1 -PythonExecutable $pythonExe -BuildRunId '<本次构建编号>'
# 开发模式加 -Development；中文空格构建加 -ChinesePath。
```

正常关闭时创建入口输出的本次 `request-stop` 文件。不要结束全局 Node／Edge 进程，也不要把历史失败候选或 T01 样片收据作为 T03 资格。

## 5. 本轮正式结果

| 类型 | 构建编号 | 验收编号 | 结果 |
| --- | --- | --- | --- |
| 普通路径 | g5-t03-build-20260920-184439-778 | g5-t03-test-20260920-184747-248 | 两入口 passed；十组通过 |
| 中文空格路径 | g5-t03-build-20260920-184747-244 | g5-t03-test-20260920-185000-639 | 两入口 passed；十组通过 |

两个构建都重新完整计算 137.4 GB PMTiles 的 SHA-256 并匹配 T02 信任值；中文构建从 `out/tmp/G5 T03 中文 调用` 启动，两个验收从系统临时目录调用。两份候选分别绑定 33 项来源、400 个发布文件和同一 T02 地形资格；来源、工具与正式后端／网关均复查。所有入口的进程环境和调用目录保持，未切换正式指针。

普通候选 manifest SHA-256 为 `370ef8a39bac98f5741f9ff7ed7cbf2c6c3ab4fd7f2d18d343b823fda804d030`，[验收收据](../out/runs/g5-t03-test-20260920-184747-248/acceptance.json) SHA-256 为 `5641e65b65efe00b2adc728a4334ae51d1160b0f25562009e9d5f8a7a75c0da0`。中文候选 manifest SHA-256 为 `5ab5e07d4340c7dd702509ec23bd7d75b9277f176d8a39ed530dcdfc2a7625c7`，[验收收据](../out/runs/g5-t03-test-20260920-185000-639/acceptance.json) SHA-256 为 `5a35db8073b8ee9a36714081cc88eb0db1f3f5114d9d9f496388cb04cdc3ba90`。`mapResourcesQualified=true`，`simulationDisplayQualified=false`、`stageQualified=false`。

十组覆盖：独立格式／地形／缓存、HTTP Range 与实际字节、HTTP／WS 代理、断网浏览、真实在线影像及受控阻断、重复启停、开发服务、缺失字体页面拒绝、坏资源启动拒绝、端口冲突与正常退出。单元组内另有十项检查，包括八个真实 MVT 瓦片与独立 Python 解码对照、uint64／损坏 protobuf、解压限制、Hilbert 次序、独立重心坐标和相邻地形节点。

| 实测项目 | 结果与含义 |
| --- | --- |
| 地形插值 | 八个独立参考点的最大数值差 `5.5706550483591855e-11 m`；不是 DEM 绝对精度，也不消除显示重采样误差 |
| 地形边界 | z8／10／12／14 东西与南北共边逐节点一致，HTTP 另查 65 个共边节点 |
| Range 服务 | 普通矩阵 299 次 Range、12,268,908 字节，总体单次最大 151,338 字节；中文矩阵同样未越界；无整包 HTTP 下载 |
| 地形缓存 | 两矩阵实测峰值均 1,081,600 字节，达到 64 片上限后淘汰；HTTP 实测并发峰值 8 |
| 浏览器缓存／并发 | 普通断网刷新后的 Range 缓存峰值 1,659,061 字节、目录缓存 5,928,320 字节；工作线程最多 4、地形请求最多 8；另有强制淘汰单元检查 |
| 中文与离线 | 实际北京底图地名、字体加载、全球／区域切换及刷新通过；断网采用浏览器外部 DNS 阻断，回环资源可用 |
| 在线与失败恢复 | 两矩阵均获取真实 Esri 瓦片 HTTP 200，随后阻断服务并恢复本地矢量；本地协议夹具持续存活，未发送仿真控制 |
| 浏览器与渲染器 | Edge 153.0.4234.32，实际报告 `ANGLE (NVIDIA, NVIDIA RTX 4000 SFF Ada Generation (0x000027B0) Direct3D11 vs_5_0 ps_5_0, D3D11)` |
| 内存记录边界 | 普通断网最终页面报告 JS 堆约 28.5 MB，仅为该时刻的浏览器 JS 堆读数，不是进程总内存或 GPU 内存；规模／FPS／CPU／GPU 测量归 T10 |
| 退出 | 两矩阵中所有正式浏览器和服务均正常退出；8000／8080／5173／9223 重新独占绑定通过；开发失败记录不计入通过 |

页面证据包括 [区域](../out/runs/g5-t03-test-20260920-184747-248/browser-offline/region.png)、[地形近景](../out/runs/g5-t03-test-20260920-184747-248/browser-offline/terrain-detail.png)、[北京中文底图](../out/runs/g5-t03-test-20260920-184747-248/browser-offline/beijing.png)、[在线影像](../out/runs/g5-t03-test-20260920-184747-248/browser-online/satellite.png) 和 [失败回退](../out/runs/g5-t03-test-20260920-184747-248/browser-online/fallback.png)。此为 T03 实际资源显示，未替代真实实体任务联调或 T11 本轮人工确认。

日常 `run-g5-map.ps1` 另从系统临时目录启动中文候选，重新取得后端基线 `g3-t01-check-20260920-185120-206`。运行 `g5-t03-serve-20260920-185119-976` 与独立 [入口浏览器记录](../out/runs/g5-t03-native-entry-browser-20260920/result.json) 均 passed，创建本次 request-stop 后 Node、Python 和 PowerShell 正常结束，环境／目录保持。当前可用候选编号如上表，默认页面地址为 `http://127.0.0.1:8080/`；本轮收尾已关闭服务。
