# G5-T04 真实地形后端资格

日期：2026-09-20，Asia/Shanghai。**G5-T04 已完成，后端真实地形资格通过。** 本卡只处理合格区域的后端地形、独立场景和三类小规模任务；Cesium 真实业务接入归 T05，原两实体及 20 实体完整联调分别归 T09／T10，阶段人工确认与前端发布归 T11。

## 1. 输入与场景

消费 [T02 区域资格](g5-geography-validation.md) 和 [T03 地图资格](g5-map-validation.md)，复查正式 AMASE／UxAS、网关和日常入口。入口配置为 [g5-backend-terrain.json](../config/g5-backend-terrain.json)。原 USGS、Copernicus、PMTiles、Terrarium 归档、模型原件和 G4 零高程基线均保持；本卡不升级工具或修改既有后端源码。

标准化 WGS84／EGM96 正高是共同高程依据；将合格 DTED 复制到每次 AMASE 运行的 data/g5-dted，TerrainConfigurator 显式加载。新建 original、small、mixed20 三份独立场景：原两实体关系、三实体 line／point／area，以及固定 8 线／6 点／6 区域。原 90 点水道、实体平面位置、矩形尺寸、任务要求和执行分配保留。

以三份场景的联合平面包络为共同飞行范围，计入矩形半对角线后向外扩 5 公里，统一冻结本轮高度适配。包络为西经 121.07998433012712～120.0604893190823 度、北纬 45.256637867916204～45.82293749930727 度，完全在 T02 合格范围内。标准化最高值 989.7364501953125 米、DTED 最高值 990 米；原最低飞行高度 700 米，因此统一加 390 米，最低飞行高度 1090 米，量化后配置净空为 100 米。该规则用于功能适配，不进行覆盖参数寻优。

914 个场景地面任务点按共同网格双线性赋高，明确为 MSL／EGM96；完整差异在准备候选 adaptation.json 中逐项记录。标准化正高以 float32 原节点保存，计算采用双精度标量权重；两端地形、任务几何和飞行高度不重复叠加 N96。初始 NominalAltitude、实体位置和巡航命令高度使用同一抬升量，性能上下限不随之改动。

## 2. DTED 实际调用与传感器边界

已确认的正式 DTEDTile 缺陷仍保留：负数按补码误读，−100 米被读为 −32668 米；dlat／dlon 将十分之一角秒按角秒解析，扩大十倍。本卡区域 DTED 为非负，准备及运行资格继续拒绝负值。最近邻／双线性通过节点数定位，中心射线步进使用 getPostSpacing(1)=3/3600；本轮调用不消费错误间距字段，不将这一限制登记成缺陷已修复。

运行独立编译 [TerrainProbe](../scripts/g5_backend/TerrainProbe.java)，安装本次专用缓存包装器。合格查询委托正式 DTEDCache／DTEDTile，不替换高程、飞行、相机或统计算法。包装器记录有上限的查询和射线样本、实际调用类别及累计计数，并拒绝越界、缺地形和负值；加载的 DTEDTile／DTEDCache JAR 来源须与正式包相同。场景在 1 秒创建配置、1.4 秒注入初始状态之前的 (0,0) 占位查询单独计数，不作为实际飞行或地形资格样本。

实际参与路径包括 KinematicFlight 的地面高度检查、CameraControl 的中心射线地形查询，以及 SearchTaskAnalysis 导出分析时按飞机位置查询地形、计算离地高度。AnalysisManager 在导出报告时重放本次原始事件，不要求 SearchTaskAnalysis 在飞行过程中实时累计。

相机仍采用原有近似：中心射线按 DTED 步进求交，四角足迹按该中心高度建立局部平面投影，角点 Altitude 写为零；Centerpoint 也不能作为独立真实地面高程依据。这里的零是旧字段表达，不能据此判断 DTED 未加载，更不能宣称四角已分别与三维地形精确求交。覆盖统计用实际足迹的平面多边形和飞机位置的地形离地高度筛选 GSD，不新增逐栅格地形遮挡算法。上述限制随 G5 交接保留。

## 3. 实现与独立验收方法

[准备实现](../scripts/g5_backend/prepare.py) 在锁定地理环境中生成候选；[运行实现](../scripts/g5_backend/runtime.py) 复用已验证的受控启动屏障及规划编排，使用正式后端、原 ExecutionProbe 和 CompletionProbe 留存实际命令、内部导航、完成事件和分析记录。三实体同时执行固定一架一任务，两模式分别真实 1 倍运行至三个 TaskComplete 和之后的终端状态，随后暂停、导出分析并正常退出；本卡不运行 20 实体稳定性或 Cesium 页面。

[独立检查](../tests/g5_backend/checks.py) 用标准库直接读取 DTED 符号幅度、列校验和、节点和共边，不调用生产地理采样器；比较全部共同网格与量化节点、原始／适配 XML、任务赋高和固定净空规则。运行后核对实际载入的 JAR、配置／地形及证据摘要，逐架关联请求、规划、命令、内部目标航点、真实移动和正确身份的完成事件；实际规划及飞行越界、低于净空或异常收尾均失败。

[统计复算](../tests/g5_backend/statistics.py) 保留既有独立平面几何检查，新增从 DTED 独立查询飞机所在位置的地面正高，按 altitude−terrain 重建 GSD 约束，逐栅格核对 20 米线／区域覆盖；点任务按同传感器连续有效样本区间合并复算观察时间。计算窗口为本轮实际采样窗口，不解释成任务完成瞬间值；所有实际传感器的原生统计与指定执行实体贡献分别记录，不设最低覆盖率或观察时长。

## 4. Windows 原生入口

仓库根目录执行下列命令；也可从其他目录传入完整脚本路径。解释器须为已核查的 Python 3.14.7 x64，工具仅在进程内启用。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\prepare-g5-backend.ps1 -PythonExecutable $pythonExe
# 使用上一条实际输出的准备编号；默认依次运行 Headless 和 Gui。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g5-backend.ps1 -PythonExecutable $pythonExe -BuildRunId '<准备编号>'
# 独立验收本次已正常结束的两模式运行。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g5-backend.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<准备编号>' -FlightRunId '<运行编号>'
```

可显式传 BaselineRunId，但仍重新核查实际来源；省略时先运行正式基线入口。单模式诊断使用 run 的 Mode Headless／Gui，完整独立资格要求两模式均通过。端口固定为 Headless 的 5556／9999／19400／19500／19600，Gui 的 5555／9999／9400／9500／9600；冲突失败，不静默换端口或结束其他进程。每模式自动预算 2700 墙钟秒，终止兜底只记失败。

## 5. 实际结果与收据

准备 `g5-t04-prepare-20260920-195013-339`、两模式运行 `g5-t04-run-20260920-195027-645`、独立验收 `g5-t04-test-20260920-201626-019` 的 result／entry-result 均 passed。准备与运行从仓库根调用；最终验收从 `out/tmp/G5 T04 中文 验收调用` 调用，省略 BaselineRunId，取得新正式来源基线 `g3-t01-check-20260920-201626-239`。PowerShell 与 Python 退出 0，调用目录／进程环境保持。

候选固定 37 项实现输入和 113 个文件，绑定 T02／T03 双编号、正式 AMASE／UxAS、网关和环境。全部 DTED 节点整米量化误差不超过 0.5 米，1201 个共边、914 个任务点、三个场景平面几何及六项准备拒绝通过。原两实体／20 实体副本仅完成准备，本卡实际飞行使用 small 的三实体；不据此登记 T09／T10。

| 模式 | 线 3000／实体 400 完成毫秒 | 点 3001／实体 500 完成毫秒 | 区域 3002／实体 600 完成毫秒 | 最后 Running 毫秒 | 最低实际采样净空 |
| --- | --- | --- | --- | --- | --- |
| Headless | 752969 | 131640 | 120410 | 756169 | 340 米 |
| Gui | 752969 | 131640 | 120410 | 756169 | 340 米 |

两模式均为真实 1 倍，使用 72／15／5 个航点的三份规划；单次任务注入、请求身份、规划分配、实际命令、内部航段、真实移动与唯一正确完成事件全部关联。任务完成后实体继续终端飞行，最终等待全部完成后三秒再暂停导出。

| 模式 | 线覆盖格数 | 区域覆盖格数 | 点观察时间复算 | 原生点报告 |
| --- | --- | --- | --- | --- |
| Headless | 724/724 | 1250/1250 | 203.202 秒 | 203.20 秒 |
| Gui | 724/724 | 1250/1250 | 204.811 秒 | 204.81 秒 |

以上为本轮完整采样窗口的结果，不设覆盖效果门槛。统计与执行身份分开：线任务的原生联合覆盖还包含实体 500 的附带观察，指定执行实体 400 的独立贡献另存；点和区域分别由指定实体贡献。没有通过删减任务、修改覆盖条件或调参取得结果。

| 模式 | 实际地形查询 | 中心射线调用 | 独立最近邻样本 | 射线重建样本／最大数值差 |
| --- | --- | --- | --- | --- |
| Headless | 103058 | 4279 | 124，全部一致 | 40／7.90976173448e-10 米 |
| Gui | 103005 | 4279 | 124，全部一致 | 40／7.90976173448e-10 米 |

两模式都实际调用 KinematicFlight、CameraControl 和 SearchTaskAnalysis，查询范围内高程 158～755 米，初始化占位查询均为零。射线独立复算检验原算法的数值一致性，不能解释为原算法几何精度、DEM 测绘精度或三维遮挡资格。独立检查另确认运行加载的 DTEDTile／DTEDCache 来自正式 JAR，配置／DTED 及全量证据摘要保持。

候选 SHA-256：`b93d4bd70f269521987e7df7915f178d8ec3f414d2df8e92c7c7aac26e6f91af`。独立 acceptance SHA-256：`7db8a7c587606cac8353acc49b3bdd20126e860c81915e3329d1a4a4d4f1d60a`。原始 TCP、内部导航、分析事件／逐格明细、类来源、正常退出和端口释放证据位于 `out/runs/g5-t04-run-20260920-195027-645/{headless,gui}/`；独立 execution／statistics／terrain、scene-checks 和 call-audit 在验收目录。

每模式 AMASE 和 UxAS 均 exitCode=0、forcedTermination=false，正常关闭及端口释放通过。准备、捕获、独立验收三类收据分开；只有本次 acceptance 登记 `backendTerrainExecutionQualified=true`，运行捕获自身仍要求独立审计。`stageQualified=false`，未启动网关／Cesium 业务显示、人工确认或正式发布。

额外拒绝检查保存在 out/runs/g5-t04-negative-20260920-02：独立 Java 驱动直接调用本次已编译缓存包装器，北／东／南／西越界、NaN、双线性边界、缺 DTED、负高程共八项均明确拒绝；独立统计重放也拒绝仅在副本中减少一个原生 SeenCells 的坏报告。首次独立驱动漏建 SimTimer，出现空指针，补齐正常计时器初始化后通过；失败输出保留在不带 -02 的诊断目录，正式飞行与源码不受影响。

来源、基准、实际执行或统计发现问题时保留独立失败批次，按影响修复／重建／复验，不改写既有资格。本卡已登记独立后端地形资格；G5 整阶段与前端指针继续待 T11。下一卡为 T05 前端状态与真实接入。
