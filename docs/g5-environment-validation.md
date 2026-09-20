# G5-T01：环境与输入基线验收

日期：2026-09-20，Asia/Shanghai。**G5-T01 已完成；下一张任务为 G5-T02。** 本卡建立了 Windows 原生最小 Cesium 工程、隔离工具、来源及输入登记和自动验收入口。未启动 AMASE／UxAS 仿真，未转换用户地图或 DEM，未发布正式前端。

## 1. 输入与来源

实施起点 `7ca739b5c88798edb5398a9b01924423ac9c125c`。开始时跟踪文件干净，只有用户提供的 `tiles/`、`tiles.zip` 未跟踪；现已加入忽略规则，原始文件保持只读。

独立后端资格 `g3-t01-check-20260920-143951-894` 与最后复查 `g3-t01-check-20260920-144822-482` 均通过。复用了现有 `check-g3-baseline.ps1`、G4 `verify_handoff`／正式包解析与日常入口资格检查，不重新解释旧收据：

| 输入 | 本轮绑定 |
| --- | --- |
| AMASE | `g1-t04-build-20260920-024628-136806`，已正常 Finalize 的正式包 |
| UxAS | `g2-t05-build-20260920-082330-977`，发布 `g2-t07-publish-20260920-083245-918` |
| LMCP | 七模型同批生成记录、正式 Java 库、G4 消费的完整 Python 生成文件摘要 |
| 网关 | `g4-t09-publish-20260920-115418-723744`；package SHA256 `dcc6b6294ff0687ae690f6518780b2ba563339b177ba7c79b22b3aa9ff41689e` |
| 日常入口 | `session.json` 绑定 `g4-t09-release-check-20260920-115528-388842` 和当前入口源码 |

每次 G5 准备、构建、运行、验收入口均复查上述来源；不带 BaselineRunId 时新建只读后端资格收据。G4 独立环境和正式指针未改变。

[地理资源登记](../config/g5-resources.json) 保留 `tiles/tiles/planet.pmtiles`、辅助 `global-z9.pmtiles`、`tiles/dem/` 和 `tiles.zip` 的布局、已观察大小／格式、来源依据和后续资格状态。本卡仅取有限头部、字节数及修改时间，前后核对一致；`fullContentHashed=false`、`terrainQualified=false`。Protomaps 来源来自用户包及其元数据，DEM 下载器来源来自用户确认，均不冒充下载收据。未全量扫描或散列百 GB 数据，未确认验收区域或垂直基准，这些归 T02。

## 2. 固定环境

| 组件 | 实际版本／策略 |
| --- | --- |
| Node／npm | 24.21.0 LTS／11.19.0；官方 Windows x64 ZIP，项目内便携部署 |
| TypeScript／Vite／Cesium | 7.0.2／8.3.0／1.145.0；npm lockfile v3 固定 91 个包条目，含平台可选依赖 |
| 地理环境 Python | 已核查的 3.14.7 x64 创建独立 venv，基础解释器和 DLL 另记摘要 |
| Rasterio／GDAL | 1.5.1／3.12.4；Windows wheel 内含 GDAL，实际验证 PNG、GTiff、DTED 驱动 |
| PyProj／PROJ | 3.8.0／9.8.1；Rasterio 内含 PROJ 同为 9.8.1，分别记录，不能据此假定配置相同 |
| NumPy／Pillow | 2.5.3／12.3.0 |
| 其余 Python 依赖 | affine 3.0.1、attrs 26.1.0、certifi 2026.7.22、click 8.5.0、pip 26.2.1、pyparsing 3.3.2、websockets 17.1；后者供独立浏览器验收 |

锁定文件为 [Node 锁](../config/g5-node-lock.json)、[地理工具锁](../config/g5-geo-lock.json)、[哈希 requirements](../config/g5-geo-requirements.txt) 和 [前端依赖锁](../apps/cesium_viewer/package-lock.json)。Node ZIP SHA256 为 `158f7685b44de51f6c0df1d153526cbcd3e1bc739a8dfc607721cef75de9e541`，来自固定发布的官方 SHASUMS256；wheel 摘要逐项对照 PyPI JSON 元数据；npm 使用 registry.npmjs.org 固定 resolved URL 和 SHA512 integrity。

安装只消费冻结的版本及摘要。Node 解压、wheel 下载先校验；坏缓存明确拒绝，不能自动改信任值。Python 离线 `--no-index --no-deps --require-hashes` 安装，前端 `npm ci --ignore-scripts`；没有全局 npm 包或持久环境更改。工具位于 `.tools/g5/environments/<run-id>/`，与 `.tools/g4/` 隔离；实际环境清单记录 4609 个文件摘要。成功检查后更新 `.tools/g5/current.json`，旧批次及失败记录保留。

PROJ 网络下载关闭；合成缺失必需网格被明确拒绝。此时尚未选择、下载或验收真实垂直转换网格。相关官方依据：[Node 发布](https://nodejs.org/download/release/v24.21.0/)、[Vite 环境要求](https://vite.dev/guide/)、[Cesium 静态资源](https://cesium.com/learn/cesiumjs-learn/cesiumjs-quickstart/)、[Rasterio 安装](https://rasterio.readthedocs.io/en/stable/installation.html)、[PyProj 网格说明](https://pyproj4.github.io/pyproj/stable/installation.html)、[GDAL DTED 驱动](https://gdal.org/en/stable/drivers/raster/dted.html)。

## 3. 工程与入口

[最小工程](../apps/cesium_viewer/README.md) 为 TypeScript／Vite、无大型 UI 框架。生产构建复制 Cesium Workers、ThirdParty、Assets、Widgets 全目录和许可证，生成 397 个候选文件；运行生产包不依赖 Vite 开发服务器。字体只使用 Windows 本地 Microsoft YaHei，不请求远程字体；模型属于 T06，当前没有仿真实体模型。

页面明确标为“环境验证”“尚未连接仿真”，显示椭球、中文标签和异步几何样片。它只证明 WebGL、资源部署和工作线程可用，不代表本地矢量、真实地形、实体姿态或后端时间通过。Cesium 自带 approximateTerrainHeights 资源不是用户 DEM，也不构成地形资格。

[运行配置](../config/g5-viewer.json) 登记 G4 8000、生产 8080、开发 5173，全部回环地址。T01 静态服务及开发服务冲突即失败；G4 代理、PMTiles Range 服务、地形与卫星图层由 T03 实施。验收另临时使用 Edge CDP 9223，独立用户目录，正常退出后释放。

以下命令可从不同工作目录通过脚本绝对路径调用；在仓库根目录可以使用相对路径。参数 PythonExecutable 必须为已经核查的解释器：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-g5.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-g5.ps1 -PythonExecutable $pythonExe -VerifyOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-g5-viewer.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g5-environment.tests.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g5-viewer.ps1 -PythonExecutable $pythonExe -BuildRunId '<本次构建编号>'
```

可选 BaselineRunId 仍会复查来源；`build-g5-viewer.ps1 -ChinesePath` 把真实工程副本、依赖和产物置于中文空格路径。构建必须新建编号，候选在 `out/build/cesium-viewer/`；原始命令、退出码和来源在 `out/runs/`。运行入口接受本次 passed 构建，复查 candidate.json、全部文件、工具及当前输入，输出 URL 和本组 `request-stop` 的位置；另一个终端创建该文件即可正常停止。不得使用超时强杀冒充正常退出。

只有工具环境指针被发布；候选 `stageQualified=false`，没有正式 Cesium 发布指针。最终页面及地理资源资格、人工确认和发布仍由 T11 完成。

## 4. 实际验收与证据

| 检查 | 记录与结果 |
| --- | --- |
| 最终工具准备 | `g5-t01-setup-20260920-144636-058` passed；环境清单 SHA256 `f22c2d2a7eba7801800a5ecb50a3a7bb06b2f8b999a77d26a9f9f9c528e1c65a` |
| 只读环境复查 | `g5-t01-verify-20260920-144934-494` passed；从系统临时目录调用绝对入口 |
| 完整矩阵 | `g5-t01-test-20260920-145253-581` passed；从 `out/tmp/G5 入口 中文` 调用，14 组检查全部通过 |
| 公开构建入口 | `g5-t01-build-20260920-145303-771` passed；系统临时工作目录＋中文空格工程；此前 `g5-t01-build-20260920-144822-264` 从中文调用目录自动重做后端资格 |
| 公开运行入口 | `g5-t01-serve-20260920-145331-517` passed；实际 Edge 加载／刷新，正常停止，详见其 result、entry-result 和 public-entry-edge 收据 |

14 组包括：声明端口空闲、独立地理能力、普通／中文两次干净构建、两次生产页面、生产重复启停、中文开发页面、缺依赖拒绝、修改来源拒绝、非白名单 npm 来源拒绝、错误下载摘要拒绝、8080 和 5173 占用拒绝。合成地理能力另覆盖 Terrarium 正负数、1201×1201 DTED Level 1 往返、无效值、坐标网格、WGS84 到 ECEF，以及缺失转换网格拒绝。

三次矩阵浏览器均为 **Edge 153.0.4234.32**，实际 WebGL 渲染器为 `ANGLE (NVIDIA, NVIDIA RTX 4000 SFF Ada Generation (0x000027B0) Direct3D11 vs_5_0 ps_5_0, D3D11)`；未强制关闭 GPU。外部域名解析禁用，检查页面资源请求全部来自本机，实际工作线程完成、中文标签及页面刷新通过，无 JavaScript 异常。四类静态资源另经 HTTP 字节摘要对照，缺失资源为 404。截图只作为资源／字体探针旁证，不替代后续真实联调或用户人工确认。

所有通过的服务、浏览器均退出 0、未强制结束，检查端口释放、父进程环境和工作目录不变。真实模拟未启动，不据本卡报告稳定性 FPS、任务完成或覆盖率。

## 5. 失败、纠正与边界

- `g5-t01-test-20260920-144246-503`：TypeScript 报 Cesium 未导出 VERSION 类型，改由锁定包元数据注入版本号；未放宽类型检查。
- `g5-t01-test-20260920-144359-705`：浏览器发现 favicon 404，补齐本地 SVG 图标；未忽略资源错误。
- `g5-t01-test-20260920-144453-990`：生产两类路径通过，但开发模式缺失资源被 Vite SPA 回退成 HTML；资源中间件现明确返回 404。该整组保持 failed。
- `g5-t01-test-20260920-144710-554` 首次完整通过；随后公开入口增加调用目录记录并完善使用说明，按最终来源重跑上述正式矩阵，不拿旧源码收据替代最终结果。
- 公开入口补测 `g5-t01-serve-20260920-145008-280` 的服务正常退出，但独立浏览器参数使用相对输出路径，Edge 在就绪前退出 21；探针现先解析为绝对路径。新构建、14 组矩阵及相同相对参数的公开运行补测全部通过；原浏览器 failed 收据保留，服务自身 passed 不代替浏览器通过。

所有失败运行和候选保留；未改写旧收据、生成模型或正式 AMASE／UxAS／G4 来源。没有调整用户地理数据，没有开始 T02。下一卡须核实 PMTiles／DEM 内容、验收区域和实际垂直基准，再制作同源标准化栅格及派生物；未知基准、缺数据或缺转换资源仍须停止地形资格验收。
