# G5-T02 地理数据与高程资格检查

日期：2026-09-20，Asia/Shanghai。**G5-T02 已完成，USGS 区域同源地形资格通过，T03 可执行。** 用户决定、WGS84 经纬度统一及最终验收见第 8～9 节；第 1～7 节保留原 DEM 异常及后续下载的历史记录。原始 `tiles/`、压缩包、正式后端和网关均未修改，没有切换 G5 正式地形或前端指针。

## 1. 复核结论：异常确实存在于上游 z10 数据

用户要求“再检查一下”后，使用独立 PNG 滤波／CRC 解码、Pillow 和 GDAL 三条路径读取同一瓦片，全部 65536 个像素完全一致。再通过 PROJ 的 EPSG:3857→4326 转换核对 XYZ 像素中心，确认没有行列倒置、TMS／XYZ 混淆或经纬度交换。

| 项目 | 实测值 |
| --- | --- |
| 原始文件 | `tiles/dem/10/170/365.png` |
| 像素索引 | 列 53、行 80，均从 0 开始 |
| RGB | `(112, 59, 0)` |
| Terrarium 手算 | `112 × 256 + 59 + 0 / 256 − 32768 = −4037 m` |
| 像素中心 | 经度 −120.16090393066405°，纬度 45.75171424271876° |
| 本地与两次独立上游下载 SHA-256 | `95e12d588026d764119078a56a1df4ca95096b24ab008fbd9ba48704332992c6` |
| 上游对象版本 | `CdukG_DwFo6gY5O1ezTWHL1vEVcz8pil` |
| USGS 同位置查询旁证 | 144.540847778 m；响应 rasterId=52124、resolution=1、AcquisitionDate=6/3/2020 |

公式来自 [Terrarium 格式说明](https://github.com/tilezen/joerd/blob/0b86765156d0612d837548c2cf70376c43b3405c/docs/formats.md)。[上游原始瓦片](https://elevation-tiles-prod.s3.amazonaws.com/terrarium/10/170/365.png) 和带版本号的 S3 下载与本地逐字节相同。因此重新下载同一对象不能消除异常。

同一位置的上游 z8／z9／z10 像素分别为 −102／−1913／−4037 m，z11／z12 为约 143.66／144.08 m。z11／z12 的来源头改为 NED／NED13，不能把这些层级直接替代已固定的 z10，也不能把不同垂直基准的数据直接拼接。USGS 查询同样仅作异常旁证，未用于补值或地形转换；本轮没有认定它与 z10 具有相同基准或相同采样分辨率。

原始像素与派生节点的数值需要区分：3 角秒标准化节点在 `(-120.16083333333333, 45.751666666666665)` 的双线性结果为 **−3718.70297764 m**。独立 PNG 解码、PROJ 像素坐标及标量四点复算为 −3718.70297766 m。前述约 −3719 m 是重采样结果，并非原始最低像素。完整候选网格有 91 个负值节点；不把“负值”普遍等同于地理错误，但这个区域的深低点及当前 AMASE 负高程兼容问题均不允许静默放行。异常生成的具体上游原因尚未查明，不能直接断言是 NoData 污染。

独立证据：`out/runs/g5-t02-independent-recheck-20260920/recheck.json`、对应下载原始字节；跨级别对照在 `out/runs/g5-t02-anomaly-investigation/samples.json`。这些记录均为诊断，`dataQualified=false`。

## 2. 已完成的输入核查

正式后端、G4 网关与入口、七模型、G5 独立工具已复查。T01 VerifyOnly 为 `g5-t01-verify-20260920-150718-453`，其后端资格为 `g3-t01-check-20260920-150718-681`。正式 T02 准备入口另外重新生成当前后端资格，不复用历史状态代替检查。

| PMTiles | 全量 SHA-256 | 索引检查 |
| --- | --- | --- |
| `planet.pmtiles`，137370745450 字节 | `b4c4674234ae75c8fea8a10c23f1cce49626155f56a437eda89b006f1e02b2b7` | 177280509 条记录、135393326 个独立内容、1431655765 个覆盖瓦片、2918 个目录 |
| `global-z9.pmtiles`，1557952591 字节 | `8a2bd6bde6a673964c5b85393d5b4a61396e44b98608edc7b1bb82a4c26ce33f` | 179074 条记录、97590 个独立内容、349525 个覆盖瓦片、45 个目录 |

全量字节摘要、完整索引、区段边界、目录覆盖、去重引用的精确起止位置及头部计数通过。采用有界目录解压、磁盘映射索引，主包临时索引约 1.08 GB，未整体装入内存。各层级取俄勒冈和北京代表性 MVT，检查 UTF-8、图层、属性字典和几何命令。**这不是全世界所有瓦片 payload 的逐一解码验收，也不是原始下载来源的独立签名证明。** 参考 [PMTiles v3 规范](https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md) 和 [MVT 规范](https://github.com/mapbox/vector-tile-spec/blob/master/2.1/vector_tile.proto)。

完整摘要原记录为 `out/runs/g5-t02-full-digest-20260920/result.json`，完整索引初验为 `out/runs/g5-t02-index-investigation/`；正式准备再次执行全量摘要和索引核查，保留独立收据。`tiles.zip` 仅保留原始归档，本轮消费解压后的数据，不把归档登记写成压缩包全量验收。

正式准备遍历 z0～10 的全部目录，1398101 个期望 XYZ 文件名齐全，逐文件检查类型及非空长度；另解码区域 35 个输入及各层级代表性瓦片。文件名覆盖检查不等于对全部 1398101 个 PNG 做解码或高程资格检查。

## 3. 区域与垂直基准

候选存储范围为经度 `[-122,-120]`、纬度 `[45,46]`，常规查询西／南闭、东／北开，外边界网格节点仅供插值。原两实体和固定 20 实体的 912 个初始位置／航点／任务几何点（含矩形角点）范围为：

- 西 −121.0083254511704°、南 45.30657536722347°、东 −120.132148198039°、北 45.775249094551334°。
- 外围 5 km 的候选包络：西 −121.072253228343°、南 45.26158598300984°、东 −120.06836203615457°、北 45.820234415768496°。

本轮保留全部平面几何，未生成飞行高度适配或修改场景。上述范围是输入几何包络，不能预测规划／实际飞行；T04 仍须检查规划、航迹及其所需外围范围，不得越出合格区域。严重异常位置在二十实体场景包络内，不能通过只剔除远处存储边缘绕过。

包含插值边缘所需的 z10 瓦片为 x=164～170、y=364～368，共 35 个；完整瓦片足迹约 `[-122.34375,44.8402906514,-119.8828125,46.0732306254]`。全部本地摘要与上游对象一致，固定版本号及 imagery-sources 来源头在 [来源锁](../config/g5-geography-lock.json)。该事实证明文件身份，不证明每个高程值正确。

上游头部包含 SRTM 与 GMTED。不能仅凭 Terrarium 编码或 GMTED 名称推断统一基准。本轮从 [USGS GMTED 页面](https://www.usgs.gov/coastal-changes-and-impacts/gmted2010) 下载官方 Spatial Metadata ZIP，完整 SHA-256 为 `9846a39b3e4f930c1df0076d91eb978dfb0b8fdb7fcf42c4446e53022edd9f34`；流式解析 SHP／DBF，选出足迹覆盖的 12 个完整来源矩形，检查连续覆盖。当地记录均为 `SRTM DTED2 Void Filled`、WGS84、EGM96、米；区域外来源并不一定相同。直接 SRTM 的基准依据为 [USGS/NASA SRTM 指南](https://lpdaac.usgs.gov/documents/179/SRTM_User_Guide_V3.pdf)。

EGM96→WGS84 椭球高采用 `h=H+N`，锁定 NGA 的 `us_nga_egm96_15.tif`，2710815 字节，SHA-256 `db493027562c9b004d7220fa881f5603adada4e1c5029b933fa7de4547b0e78d`；来源摘要为 [PROJ 官方清单](https://cdn.proj.org/files.geojson)，许可见 [NGA 网格说明](https://github.com/OSGeo/PROJ-data/blob/master/us_nga/us_nga_README.txt)。使用显式网格、关闭 PROJ 网络，缺失或摘要改变即失败。

本轮只能确认上述区域的数据来源／垂直基准路径。地形数值异常尚未解决，**基准核实不等于地形资格通过**。

## 4. 工具与独立检查

[只读核验／派生实现](../scripts/g5_geography/worker.py) 和 [区域配置](../config/g5-terrain.json) 实现：Terrarium 像素中心采样、3 角秒标准化正高网格、DTED Level 1 整米量化、Cesium 椭球高度场、来源／产物摘要及明确拒绝。所有真实输入只读；发生异常时不生成合格 manifest。

`g5-t02-core-20260920-03` 的 25 项实现检查通过，但 `dataQualified=false`。包括：

- 损坏／截断 PNG、CRC、NoData、缺瓦片、缺网格、改网格、未知高程基准、重复改正、经纬度交换和越界拒绝。
- PMTiles varint 溢出／截断、gzip 上限、目录长度、MVT 截断及独立 Hilbert 已知顺序。
- 真实异常瓦片三种解码一致、原始像素到标准化节点的独立数值复算。
- 中文空格路径中的**合成**完整派生与 DTED 所有列校验，2883601 个标准化节点，GDAL 独立往返。
- 四个独立样点的 geoid 数值差最大约 0.000025 m；正式 AMASE 最近邻误差 0、双线性误差约 4.6×10⁻¹³ m；实际固定 Cesium HeightmapTerrainData 五点三角插值与独立三顶点平面求解误差约 6.6×10⁻¹² m。不同插值方法分别对照，没有要求它们彼此逐位相同。

上述数值描述转换实现，绝不代表源 DEM 绝对精度。源 z10 像素间距、标准化 3 角秒间距、DTED 整米量化、20 米覆盖统计栅格为不同概念。

测试也实际证实两项 AMASE 既有问题：标准 DTED 的 −100 m 被正式 `DTEDTile` 读成 −32668 m（按二进制补码读取了符号幅度编码）；其 dlat／dlon 字段把十分之一角秒直接除以 3600，得到十倍间距。当前查询以节点数计算位置，正值样本正确。源码未改、正式 JAR 未重建；资格守卫拒绝负高程，不能用错误负值继续仿真。后续如需修复，按 T04 的后端来源／重建规则处理，不能只改编译产物。

实现检查曾发现并修正两个本轮代码问题：PNG CRC 失败抛出的 Pillow SyntaxError 统一转换为明确数据异常；显式 `multiplier=1` 与 `+inv` 同时使用导致 geoid 符号反转，已去掉 inverse，并用 GDAL 网格标量求值独立复验。这两个问题不改变原始 −4037 m 或正高重采样 −3718.70 m 的异常结论，旧失败记录保留。

## 5. 复现入口与后续条件

从仓库根执行；工具仅在项目子进程内使用：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\prepare-g5-geography.ps1 -PythonExecutable $pythonExe
```

当前数据预期在地形资格处失败，详见本次 `out/runs/g5-t02-prepare-20260920-154127-213/` 及同名 `out/geography/` 目录。入口从不同工作目录调用，先复查当前后端／网关／工具，再校验数据；失败结果不能作为后续资格输入。`tests/windows/g5-geography.tests.ps1 -BuildRunId ...` 仅接受成功的同源候选，目前没有符合前提的真实候选。

本次实际运行已完成：`result.json`、`worker-result.json`、`entry-result.json` 均为 failed，公开入口退出 1；`terrain-rejection.json` 保存全部 91 个负值节点、坐标和原始数值，`automaticFillApplied=false`。进程环境及调用目录保持，未启动仿真。后端资格 `g3-t01-check-20260920-154127-456` 为 passed。这是按数据问题拒绝的运行结果，不能写成 T02 验收通过。

后续拒绝检查 `g5-t02-test-20260920-154638-284` 实际以该失败准备编号调用，明确报 `Candidate entry did not pass`，公开入口退出 1，未产生 acceptance 或合格指针。失败前驱不能被后续入口放行。

独立异常复查与实现探针（输出目录必须为新的路径）：

```powershell
$envPointer = Get-Content .\.tools\g5\current.json -Raw | ConvertFrom-Json
$geoPython = Join-Path (Join-Path (Get-Location) $envPointer.path) 'geo/Scripts/python.exe'
& $geoPython -I -B -X utf8 .\scripts\g5_geography\recheck.py --root . --output out/runs/g5-t02-my-recheck --online
& $geoPython -I -B -X utf8 .\tests\g5_geography\validate.py --root . --output out/runs/g5-t02-my-core-check
```

首次复核结束时尚缺：真实有效地形数据、通过资格的真实标准化栅格／DTED／Cesium 高度场、真实输入边界／接缝及完整派生资格。当前合成输出不可交给 T03 或 T04。该次用户只要求重新核查，未确认修复或更换数据路线；没有执行补值、降级到其他 zoom、改动验收区域或切换数据源。后续双来源下载见第 7 节；仍须明确转换依据和可审查差异，再用新编号重新走完整 T02，保留原失败收据。

本轮未完成任务卡，不触发“完成并验收后自动提交／推送”。与本任务无关的用户 `models/` 文件保留。

## 6. 替代数据调查（2026-09-20 补充）

用户确认源 DEM 存在问题并询问替代数据。本次只查资料、HTTP HEAD 和通过 Range 读取 GeoTIFF 元数据／局部窗口，没有替换输入、下载完整区域包或修改地形配置；T02 继续受阻。

| 候选 | 数据含义及基准 | 本项目适用性 |
| --- | --- | --- |
| USGS 3DEP 1/3 角秒 | 标称约 10 m 的裸地高程；美国本土采用 NAVD88，实际候选文件水平 CRS 为 NAD83／EPSG:4269 | 优先考虑当前俄勒冈验收区；需核实水平／垂直转换链再转入统一标准化基准 |
| Copernicus GLO-30 | 标称约 30 m 的 DSM，包含植被、建筑等表面；WGS84／EGM2008 | 适合后续跨国及全球覆盖；明确 DSM 语义，并增加 EGM2008 到项目标准基准的转换 |
| NASADEM_HGT | 1 角秒、EGM96 的 merged HGT，SRTM 重处理产品，覆盖约 56°S～60°N | 可作为 EGM96 备选；未下载或核查本区域实际产品，不能与 SRTM-only 椭球高产品混淆 |

依据：[USGS 3DEP 标准](https://www.usgs.gov/3d-elevation-program-standards-and-specifications)、[USGS 无缝 DEM 规范](https://pubs.usgs.gov/tm/11b9/tm11B9.pdf)、[Copernicus 官方产品说明](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)、[Copernicus 公共下载登记](https://registry.opendata.aws/copernicus-dem/)、[NASADEM 用户指南](https://lpdaac.usgs.gov/documents/2237/NASADEM_User_Guide_V13.pdf)。这些间距不是高程精度承诺。

实测 USGS `n46w122`／`n46w121` 两幅文件均公开可读，合计 896605235 字节；Copernicus `N45_00_W122_00`／`N45_00_W121_00` 两幅公共 COG 合计 84695229 字节，均支持 Range。上述为场景核心区域两幅文件大小，正式派生边缘需要的邻接瓦片须另行计算；尤其 Copernicus 去重后的边界节点不能假定由两幅文件完整提供。AWS Copernicus 公共副本登记为 2021 release，不把它等同于当前 CDSE 最新发布。

同一异常位置读取 3×3 邻域，USGS 10 m 像素为 **144.5237274 m**，Copernicus 30 m 像素为 **142.8855591 m**，邻域没有复现旧瓦片的数千米低点。这只是未统一基准、未统一采样位置／方法的局部诊断，不能据这两个数值判断哪份数据高程误差更小，也不能据单点宣布整区合格。

来源 URL、文件长度、ETag、Last-Modified、栅格布局、CRS 及原始窗口值保存在 `out/runs/g5-t02-alternative-research-20260920/{availability,metadata-samples}.json`。建议当前验收区优先评估 USGS 3DEP，若要求后续全球统一来源则优先评估 Copernicus；尚未选定替换路线，也未更改“真实地形资格失败”的结论。

## 7. 两套区域数据下载（2026-09-20 补充）

用户明确要求“USGS 3DEP 和 Copernicus 都要，下载吧”。本次完成两套区域源文件下载、来源附件留存与完整性验证；不执行标准化、基准转换、DTED 派生或正式来源切换。

批次 `g5-t02-dem-download-20260920-160406`，数据位于 `out/geography/sources/g5-t02-dem-download-20260920-160406/`，过程位于同编号 `out/runs/`。数据及来源附件共 **1,150,673,653 字节**（约 1.15 GB，不含收据和脚本）。最终入口为数据目录的 `verified-manifest.json`；`SHA256SUMS.txt` 列出全部 15 个文件摘要，`integrity.json` 为通过收据，明确 `terrainQualified=false`。

| 数据目录 | 实际文件与范围 | 栅格大小 |
| --- | --- | --- |
| `usgs-3dep-13arcsec/` | `USGS_13_n46w122.tif`、`USGS_13_n46w121.tif`，另附各自 XML 和 GPKG 来源范围文件；逐瓦片 XML 发布日期为 2026-02-02，NAD83／NAVD88／米 | 2 幅，共 896,605,235 字节 |
| `copernicus-glo30/` | `N45`／`N44` × `W122`／`W121`／`W120` 六幅；AWS 公共 2021 release 的 COG，WGS84／EGM2008／米，DSM | 6 幅，共 247,571,242 字节 |
| `documents/` | Copernicus 公共 COG README、GLO-30 许可证、USGS 无缝 DEM 规范 PDF | 3 份，共 4,200,863 字节 |

下载范围围绕原定经度 [-122,-120]、纬度 [45,46] 的存储网格。USGS 两幅本身有外围像素。Copernicus 原始相邻共享的东／南行列在公共 COG 中被移除，因此两幅核心瓦片之外加入 `N44` 和 `W120` 邻接瓦片，供纬度 45°、经度 −120° 的外边界节点取样；不改变原场景或验收区。此规则依据[公共 COG 布局说明](https://copernicus-dem-30m.s3.amazonaws.com/readme.html)。水平转换后的覆盖及重采样边界仍须在正式派生时核查。

下载前冻结 HTTPS URL、Content-Length、ETag、Last-Modified；GET 使用 If-Match，写入独立 `.part` 后核对长度并计算 SHA-256。最终另行完整重读核验 SHA-256；USGS 大文件核对服务端 `x-amz-meta-md5chksum`，没有把分段 ETag 当作 MD5，其余十个源文件核对普通 S3 对象的单段 MD5 ETag。判别依据 [S3 ETag 文档](https://docs.aws.amazon.com/AmazonS3/latest/API/API_Object.html)。未声称存在发布方 SHA-256 签名；本地 SHA-256 用于后续锁定本次文件身份。

在 T01 独立地理环境下，8 幅基础分辨率栅格逐块解码共 **311,558,688 个像素**，同时读取内部概览，均无解码错误；基础栅格未发现 NoData 或非有限值。两份 XML 解析及两份 GPKG SQLite 完整性检查通过。原异常位置的本地读取仍分别为 144.5237274 m 和 142.8855591 m，保留各自原生基准，仅作诊断。全文件可读和局部高程合理不代表转换、接缝、绝对精度或真实仿真资格通过。

首次校验因 USGS 规范 PDF 请求返回 403 而退出 1；12 个数据／元数据文件此前已通过。改用 PowerShell HTTP 客户端从同一官方 URL 取得 4,078,541 字节 PDF，单独保存 `supplemental-documents.json`，保留原下载收据中的失败记录。随后完整重跑 `out/runs/g5-t02-dem-download-20260920-160406/verify.py`，退出 0、`integrity.json` passed。第一次失败摘要为 `integrity-attempt-01.json`；没有修改源栅格或跳过缺失文件。

下一步属于 T02 的候选评估与转换资格：确认实际使用来源、核查 NAD83／NAVD88 或 EGM2008 的转换资源、统一标准化栅格，再生成同源 DTED／Cesium 并独立检查。当前 `config/g5-terrain.json` 和既有锁仍描述旧 Terrarium 输入，不能把新下载目录直接当作已通过的替代品。原始数据、失败收据、G4 零高程基线及正式指针均保留；T03 继续等待 T02。

## 8. 用户决定与 WGS84 同源实现

用户随后明确采用“原矢量底图＋USGS 区域主地形，Copernicus 用于对照”，并要求继续实施；另询问的“GSM84”按地理语境解释为 WGS84。本轮统一经纬度，保持 AMASE 正高语义和 Cesium 椭球高语义，从共同网格派生。第 1～7 节保留先前异常、调查和下载时的历史状态，本节记录新决定及实现。

| 环节 | 固定坐标与高程定义 | 数据用途 |
| --- | --- | --- |
| USGS 源文件 | NAD83／NAVD88，`EPSG:4269+5703` | 唯一区域主地形，双线性读取原生像素中心 |
| 标准化 GeoTIFF | WGS84 经纬度／EGM96 正高，`EPSG:4326+5773` | 2401×1201 个 3 角秒节点，float32；两端的共同高程依据 |
| AMASE DTED | 相同 WGS84 网格／EGM96 正高 | 两幅 1201×1201 Level 1；从共同网格四舍六入五取偶到整数米 |
| Cesium 高度场 | WGS84 椭球高，`EPSG:4979` | 从共同正高网格按 `h=H96+N96` 转换一次，float32 小端 |
| Copernicus 对照 | WGS84／EGM2008 转到 WGS84／EGM96 | `H96=H2008+N2008−N96`；不填补、平均或替换主地形 |

源身份与转换资源固定于 [区域来源锁](../config/g5-regional-sources.json)，[区域配置](../config/g5-terrain.json) 定义主／对照角色、范围、间距、插值及残差限值。[USGS 坐标操作](../config/g5-usgs-operation.json) 保存 PROJ 的完整操作定义；原 Terrarium 的配置另存于 [历史配置](../config/g5-terrarium-legacy.json)，仅用于异常回归与合成实现探针。T01 的 `config/g5-resources.json` 仍是历史原始输入登记，不能代替本卡候选及验收收据。

USGS 转换采用固定 PROJ／EPSG 数据库 v12.029 为该区域提供的非 ballpark 操作：NAD83→NAD83(HARN)（EPSG:8556，NADCON5）→NAVD88 正高到 HARN 椭球高（EPSG:9160 逆，GEOID99）→WGS84（EPSG:1901），再减 NGA EGM96 改正得到标准化正高。选择依据是源文件明确声明的 NAD83／NAVD88 与已登记操作匹配，不把 NAD83 擅自重标为 NAD83(2011)，也不直接套用要求该实现的 GEOID18。[GEOID18 基准要求](https://www.ngs.noaa.gov/GEOID/GEOID18/geoid18_tech_details.shtml)

该链条使用较早的 GEOID99，完整定义保留其已被后继模型替代的备注和 WGS84 框架近似说明。操作登记的模型精度为 1.1 m，加 EGM96 步骤后为 2.1 m；这是转换模型的不确定性口径，**不属于本项目“独立数值计算误差≤1 m”的判据，也不构成 DEM 绝对精度承诺**。未通过选择模型或修改统计口径宣称厘米级实测精度。后续更换模型必须作为新输入版本复验。

四份网格均由 [PROJ 官方摘要清单](https://cdn.proj.org/files.geojson) 固定 SHA-256 后取得，消费期间关闭 PROJ 网络：

- `us_noaa_nadcon5_nad83_1986_nad83_harn_conus.tif`：NADCON5 水平转换。
- `us_noaa_g1999u01.tif`：与选定操作配套的 GEOID99。
- `us_nga_egm96_15.tif`：标准化正高与 Cesium 椭球高转换。
- `us_nga_egm08_25.tif`：Copernicus EGM2008 对照转换。

完整元数据、字节数和摘要在来源锁；调查原始清单及操作定义在 `out/runs/g5-t02-usgs-datum-research-20260920/`。代码 [regional.py](../scripts/g5_geography/regional.py) 检查文件摘要、坐标／高程基准和缺值，使用有界原生窗口；固定西侧 USGS 瓦片优先，不进行来源混合。新标准化网格、DTED、高度场、接缝报告和对照结果都在独立候选目录，不修改源文件。

首次试派生 `g5-t02-usgs-development-01` 在部分 NADCON5 插值分片边界遇到严格迭代收敛检查失败。独立调查显示，增加迭代次数不能消除分片切换带来的厘米级跳变；原因与 [NADCON5 双二次插值](https://proj.org/en/stable/operations/transformations/gridshift.html) 的邻域变化一致。实现改为从四次实际求值中选择残差最小的一次，采用保守水平残差界限 0.05 m，仍远低于 1 m 数值判据，超限明确拒绝。完整网格实测最大残差上界 0.0337182 m，29 个节点超过 0.00001 m，全部记录；没有宣称转换在这些分片处逐位可逆。

第二次试派生 `g5-t02-usgs-development-02` 完整通过：正高范围 2.0935845～3418.8381348 m，全部 2,883,601 个节点有效；DTED 量化误差至多 0.5 m。USGS 两幅原生重叠区沿 −121° 的 1201 点最大差约 0.0001044 m；生成的两幅 DTED 共边节点逐值相同。

3321 个统一基准的 Copernicus 对照样点，中位差约 0.404 m、绝对差 P95 约 25.033 m、最大约 58.909 m，最大差位置和值完整保留。Copernicus 是包含植被／建筑的 DSM，这些差值不直接解释为 USGS 或 Copernicus 的测绘误差，也不用于补值或调整飞行参数。[DSM 定义及比较注意事项](https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM)

独立检查 [regional_checks.py](../tests/g5_geography/regional_checks.py) 使用原生栅格四点标量插值、3×3 节点组成的二维二次 Lagrange 多项式、手工 ECEF／Helmert／椭球反算，对照 PROJ。5 个复合转换样点最大 ECEF 数值差约 3.54×10⁻⁸ m；10 个标准化节点含外边界、瓦片共边与分片异常位置，最大高差约 0.00006455 m。此为计算实现一致性，不是地面控制点测绘精度。

## 9. 最终资格、入口与 T03 交接

正式准备 **`g5-t02-prepare-20260920-174145-970`** 与独立验收 **`g5-t02-test-20260920-174558-688`** 均 passed，公开入口退出 0；各自 `result.json`、`worker-result.json`、`entry-result.json` 一致通过。准备从 `out/tmp/G5 T02 中文 调用` 进入，验收从系统临时目录进入；工具均在子进程启用，父进程环境和调用目录保持。当前后端、正式网关、日常入口、七模型及 T01 独立工具均重新通过资格检查。

准备入口再次完整读取两份 PMTiles、检查全部索引及代表性 MVT，结果与第 2 节身份和计数一致；没有因为旧准备失败而跳过矢量检查。15 个区域源／附件文件、四份转换网格及本次全部实现／配置输入均按锁复查。独立生成原例与混合 20 实体的输入几何包络，仍为 912 个位置／任务顶点，5 km 外围完全位于既定存储范围；没有修改场景或启动飞行。

八组正式验收包括：

1. 全部同源网格节点、独立 EGM96 改正、正式 AMASE 最近邻／双线性读取及实际 Cesium 高度场插值。
2. 原 25 项格式、坏数据、旧源异常、合成实现与 AMASE 负高程拒绝回归；合成产物单独标记，不充当区域资格。
3. 独立 NADCON5／GEOID99／ECEF／Helmert 复合转换。
4. 从原生 USGS 栅格到标准化节点的独立计算，含存储外边界、共边和分片位置。
5. 两幅 DTED 的全部节点及 1201 个共享边界节点逐值对照。
6. 3321 个同基准 Copernicus 对照样点，保留差异与 DSM 语义。
7. 全网格源坐标残差上限和分片边界记录。
8. 11 项来源／边界／基准拒绝：重复改正、未知基准、越界、经纬度交换、改正网格摘要变化、下载收据变化、源文件缺失、原生 NoData、对照边界缺失，以及主源缺失时禁止改用 Copernicus。

正式 AMASE 最近邻误差为 0，双线性误差约 6.71×10⁻¹² m；固定 Cesium `HeightmapTerrainData` 与独立三角平面插值最大差约 1.63×10⁻¹⁰ m；独立 EGM96 改正和 float32 高度场最大差约 0.00003609 m。DTED 的整数米量化另记为最大 0.5 m，不与源分辨率或 DEM 测绘精度混写。

候选目录：`out/geography/g5-t02-prepare-20260920-174145-970/`。主要文件为 `orthometric.tif`、`dted/w122/n45.dt1`、`dted/w121/n45.dt1`、`cesium-heightfield.f32`、`terrain.json` 和 `manifest.json`。候选 manifest SHA-256 为 `f0f6372b16cda86811750f83df44560ec345097fbcd695ad6fb6dffa7854a8c0`；验收收据在 `out/runs/g5-t02-test-20260920-174558-688/acceptance.json`，SHA-256 为 `3294d503ef172afd3f123a0a67a6393ef3b535f2eda1247b2fd6bdb57ff22c9a`。

T03 必须成对消费上述候选和验收收据，并复核候选文件、来源配置及后端／工具身份。重新生成时在仓库根执行：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\prepare-g5-geography.ps1 -PythonExecutable $pythonExe
# 使用上一条实际输出的新准备编号。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g5-geography.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<本次准备编号>'
```

`acceptance.json` 登记 `regionalTerrainQualified=true`，同时保持 `globalSimulationQualified=false`、`backendTerrainExecutionQualified=false`、`stageQualified=false`。原下载 `verified-manifest.json` 的 `terrainQualified=false` 仍是正确的下载阶段历史状态，地形资格由本次独立 acceptance 提供；不回写下载记录或旧失败收据。G5 正式指针仍须等待 T11；本次没有 GUI 或人工确认环节。

已知限制：正式 AMASE 的 DTED 负值和间距元数据问题仍保留，本区域非负数据和两种实际查询已通过，不推广到其他区域。全球旧 DEM、在线影像、资源服务和三维页面由 T03 另验；真实地形参与飞行、传感器和 20 米统计由 T04 另验。下一卡为 G5-T03，本卡不启动页面、仿真或覆盖参数优化。
