# G5-T11 阶段验收、完整本地包与发布

日期：2026-09-24，Asia/Shanghai。**当前状态：G5-T11 已完成，G5 正式本地包已发布。** 当前页面人工确认、真实会话正常退出、正式指针和生产入口均有独立通过收据。G5-T09／T10 的双模式真实任务与资源证据见 [两实体报告](g5-full-validation.md)和 [20 实体报告](g5-scale-validation.md)。

## 来源与包

T11 以正式 AMASE／UxAS／G4 网关、G5-T02 地理派生、T03 地图、T04 后端场景、T07 页面候选、T09 原水道全程和 T10 混合 20 实体长时收据为前置。包构建 `cesium-stage-build-20260924-030247-362` 的 `result.json`、`entry-result.json`、`build-result.json` 均 passed；`manifest.json` SHA256 为 `c755b9b962b2cc1a077d64f88519cafb60819b8672fe4c6cc9f77dd7672be9e3`。包位于 `out/build/g5-stage/<编号>/package/`，包含 407 个生产页面文件、固定 Cesium Workers／Assets／Widgets、Noto CJK 字体与 OFL、许可清单、UCAV GLB／纹理、椭球高度场、地图及覆盖服务代码与配置。

全球 `planet.pmtiles` 为 137,370,745,450 字节；包内使用同卷 NTFS 硬链接，构建和独立资格均重新计算完整 SHA256 `b4c4674234ae75c8fea8a10c23f1cce49626155f56a437eda89b006f1e02b2b7`，同时核对物理文件身份、长度、修改时间与来源清单。硬链接使本机包不增加第二份 137 GB 拷贝，意味着原件就地改写会影响包；日常入口检查物理身份／长度／修改时间，变更或迁移须重新资格化。第二机器部署归 G8，当前本地包不宣称可跨机器复制后直接运行。

### 标准入口

以下命令在仓库根目录执行；所有任务编号须取当前合格收据，示例为本轮固定组合。构建与测试脚本生成独立编号，不覆盖旧候选。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
$baseline = 'g3-t01-check-20260923-214731-692'
$coverage = 'g5-coverage-build-20260922-140926-685'
$full = 'g5-t09-test-20260923-232112-235'
$scale = 'g5-t10-test-20260924-013823-667'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\cesium-stage.ps1 -Action Build -PythonExecutable $pythonExe -BaselineRunId $baseline -CoverageBuildRunId $coverage -FullRunId $full -ScaleRunId $scale
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\cesium-stage.tests.ps1 -PythonExecutable $pythonExe -BaselineRunId $baseline -CoverageBuildRunId $coverage -FullRunId $full -ScaleRunId $scale -StageBuildRunId '<BUILD_RUN_ID>'
```

独立包资格 `cesium-stage-test-20260924-030402-656` 的 result、entry-result、acceptance、打包服务 lifecycle 和离线 Edge 浏览器结果均 passed；acceptance SHA256=`5c0989eeb3b74db7fd5d8e49093d31e397ce942237552042c8750860c1159583`。前端资源、地理派生与真实运行入口三类资格均绑定同一来源，`stageQualified=false`（构建资格阶段）；本轮验证了本地矢量 Range／并发／错误拒绝、区域地形接缝、只读 API、字体／模型／许可文件、离线地图及服务正常退出；已冻结的 T03～T10 收据承担完整业务、两类路径、恢复与长时证据。

## 当前页面人工确认与正常退出

原 GUI 预览 `cesium-stage-review-20260924-030608-455` 曾完成三任务并暂停，但在会话间退出，没有正式正常收尾收据，因此保留原始记录且不用于发布。本轮按用户请求重启独立后台服务，当前预览 `cesium-stage-review-20260924-143556-061` 从候选包启动真实 GUI、正式 G4 网关及三任务地形会话，地图与网关分别使用 8080／8000，运行身份一致。三任务在 120910／133240／752969 仿真毫秒完成，756169 毫秒暂停。

用户在本轮页面查看后明确回复“一切正常”。确认记录 `cesium-stage-confirm-20260924-145527-434` 绑定当前 review、manifest SHA256 和 `approve` 决策；不是自动截图替代。入口发出正常停止请求后，`review-acceptance.json`、result、entry-result、runtime-result 均 passed，正常退出且端口释放。人工确认按当前页面的视觉反馈关闭此前累计覆盖显示疑问；覆盖几何与统计的自动资格仍以 T09／T10 独立收据为准。review acceptance SHA256=`ad84651c410dd0f600775c2b31b63dac55dd43e7f737320bf68195da08372ea9`。

## 正式发布与生产入口

`cesium-stage-publish-20260924-145557-121` 复核候选、自动资格和当前确认／正常退出后，通过 result、entry-result、acceptance 并发布至 `out/artifacts/g5-stage/cesium-stage-build-20260924-030247-362/cesium-stage-publish-20260924-145557-121/`。`current.json` 指向该包，`stageQualified=true`；发布 acceptance SHA256=`79856009d197b0a90cb6fac63224d774fe4fc25a27b83c8da13f76423d270dd5`。本地 137 GB 矢量包按同卷硬链接引用；正式包仍依赖本工作区合格后端、网关、地理派生和固定工具环境。

首次生产入口 `cesium-stage-run-20260924-145724-732` 在约 71 仿真秒时 AMASE 观测流断开，`runtime-result.json` 为 failed，未形成生产资格；同时出现执行证据写入异常。原始失败目录保留，磁盘空间充足，未能从该次日志进一步确定瞬时断开的外部原因；不改判也不计入成功。未修改已验收源码或发布包，使用同一正式指针重新运行。

重跑 `cesium-stage-run-20260924-150104-558` 的 result、entry-result、runtime-result、production-result 均 passed；三任务真实完成后自动暂停，正式入口发出正常停止请求，AMASE／UxAS、正式 G4 网关、覆盖线程与包内地图服务正常退出，8080／8000 及后端端口释放。生产收据 SHA256=`47657da9021244167e51348890bbf97ddf97b523ac445281e62ed72ad7b60ee1`，运行收据 SHA256=`d34a1c58dd264549479f0a182cc63ab166bde047197006cd2d64706a3d5727cc`，`stageQualified=true`。首次失败说明单次会话仍可能遇到观察断线；日常启动应检查当次 result 和日志，不能沿用历史 passed 收据替代。

正式启动可使用下列命令（同一组已合格前置编号）；关闭方式和日常操作见 [用户指南第 11 节](project-overview-and-user-guide.md#11-启动暂停现象与重启服务)：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\cesium-stage.ps1 -Action Run -PythonExecutable $pythonExe -BaselineRunId $baseline -CoverageBuildRunId $coverage -FullRunId $full -ScaleRunId $scale -StageBuildRunId cesium-stage-build-20260924-030247-362 -QualificationRunId cesium-stage-test-20260924-030402-656
```

第二机器部署、离线卫星影像包归 G8；G6 控制和任务规划交互见 [G5 → G6 交接](g5-g6-handoff.md)。20 实体全图高负载约 5 FPS、未达约 30 FPS 目标的实测限制仍见 [T10 报告](g5-scale-validation.md)，本轮不以该目标作为硬门槛。
