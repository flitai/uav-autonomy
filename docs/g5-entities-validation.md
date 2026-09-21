# G5-T06 实体、姿态与时间验收

日期：2026-09-21，Asia/Shanghai。**G5-T06 已完成，实体显示资格通过。** 本卡交付模型、标签、列表／详情、实际轨迹、定位／跟随／复位及大小快捷键；完整航线、任务和区域图层继续归 T07，G5 阶段发布归 T11。

当前可启动候选与显示规则见 [固定屏幕尺寸与立体光照补充](g5-model-display-validation.md)，前一配色版本见 [阵营荧光色与描边补充](g5-affiliation-display-validation.md)。下文首次 T06 批次及命令示例保留历史，使用现源码时应选补充报告中的新 BuildRunId。

## 1. 输入、工具与候选

新增 [实体模块](../apps/cesium_entities/README.md)、[构建／运行编排](../scripts/g5_entities/manage.py)、[配置](../config/g5-entities.json)及独立验收。构建把经过来源复查的 T03 地图源代码、T05 状态类和 T06 实体模块组成单一 Vite 包，共用一个 Cesium 引擎；锁定依赖、原地图／状态实现、正式 AMASE／UxAS／G4 和 T02～T05 收据保持。候选独立绑定 20 项 T06 输入、前置资格和模型工具，不更新正式前端指针。

原生读取器使用 [OpenSceneGraph 3.6.5 官方源代码](https://github.com/openscenegraph/OpenSceneGraph/tree/OpenSceneGraph-3.6.5)，压缩包 SHA256 为 `aea196550f02974d6d09291c5d83b51ca6a03b3767e234a8c0e21322927d1e12`，SHA512 与已固定 vcpkg 的 osg 配方核对。逐文件复查解包源码后，以已合格 MSVC v143／CMake／Ninja 构建 Release x64／动态 CRT；工具仅位于 .tools/g5-models，环境在进程退出时恢复。冻结清单见 [g5-model-toolchain.json](../config/g5-model-toolchain.json)。包包含读取器、必需 DLL／OSGB 插件和 OSG 许可；转换器仅对本次选用静态资产取得资格，不宣称支持任意 OSGB。

| 交付 | 本轮编号／摘要 |
| --- | --- |
| 工具构建 | g5-t06-model-tools-20260921-100741-808 |
| 工具 manifest SHA256 | f70548a479a10d1d7259ffe1bd65f248a82c7b128be0c3a68247e416351b75c1 |
| 工具只读复查 | g5-t06-model-tools-20260921-102849-073 |
| 正式后端新基线 | g3-t01-check-20260921-094741-945；日常入口另重新检查 |
| 中文空格路径候选 | g5-t06-build-20260921-102511-629 |
| 中文 candidate SHA256 | ebc0a41e05a60c05d56b9915139e23609d9b6393cabad9ed418bf07a29253715 |
| 普通路径候选 | g5-t06-build-20260921-102716-695 |
| 普通 candidate SHA256 | e14d201adbde6f3963eb22c3d828bbfeb6dd14590acc770756b8cb1fcf4adc25 |
| 中文候选两模式及地图回归 | g5-t06-test-20260921-102534-000 |
| acceptance SHA256 | 1f8fd81b8df17e41fbbc91953a6c955a07ed706d43ad93638f004e8b2fcbf0b0 |
| 普通候选联合入口 | g5-t06-session-20260921-102742-495 |

两种候选各登记 455 个文件，其中 405 个生产文件逐项同字节。原始证据位于对应 out/runs，候选位于 out/build/g5-entities；result、entry-result 和验收收据均须成功，来源变化须重建复验。

## 2. 选用模型与用户尺寸决定

用户说明模型来自 AFSIM，并明确确认 **1 源单位＝1 显示米**，要求快捷键调整大小。这是显示约定，原件没有独立单位元数据；不据此认定真实机型的测绘尺寸、重心或仿真性能。原件保留只读，16 个模型中本轮只选择 ucav_lo.osgb；未选用资产保持 [原登记](g5-model-inputs.md)。用户提供原件用于本地项目展示，不把来源声明视为对外再分发许可；T11 打包时沿用必要许可核查。

原件 SHA256：`ffb83ce6da482060a65a2eff5ef508e29398c34a1b2c9fc7e7507393cf2676c7`。读取结果为 1 个静态网格、1776 个三角形、5328 个展开顶点、128×128 内嵌 RGBA 纹理；透明度保留，无外部资源或动画。实际几何三视图核对前向 −Y、上向 +Z；保留原点作为实体锚点，不声称是重心。显示翼展约 18.962 米、纵向约 11.782 米、厚度约 1.912 米。

资产旋转为 `(x,y,z) → (x,z,−y)`，得到 glTF 前向 +Z、上向 +Y；真实 Cesium 引擎继续转换到前向 +X、上向 +Z。资产旋转与消息姿态分开。OSG 图像原点和 UV 分别转换，独立检查嵌入 PNG 像素、透明度、几何、法线、UV 及材质；漫反射映射至 PBR，metallic=0、roughness=1，不声称与旧渲染器光照完全相同。

GLB 为 **188488 字节**，SHA256 `4e7e7646fcb24656f1d944bdf9fdc4767af38d26c4f23a617dbab642c17ada51`。无需外网纹理。默认 scale=1、minimumPixelSize=0；远处有独立点标记。`+`／`=` 放大，`-` 缩小，`0` 恢复 1×；每步 √2，范围 0.25～32×，对所有显示实体生效，刷新恢复 1×。真实浏览器检查模型 primitive.scale 随快捷键变化，位置和姿态保持，未发送 WS 业务包。

## 3. 坐标、姿态和时间

当前合格 AirVehicleState 的 MSL 高度按 EGM96 正高处理。实体使用与地形相同的冻结 EGM96 网格，将 `h = H96 + N96` 改正一次；不再加地面高程。浏览器包包含验收区所需 9×5 个原始 15′ 改正节点，双线性插值与离线 PROJ 对照。未知高度基准／AGL、非有限值和越界实体拒绝显示。此范围仍限于西经 122～120、北纬 45～46 度，实体检查东／北边界不含端点。

姿态按正式 AMASE Euler 的前／右／下 → 北／东／下转换，再构造 Cesium 前／左／上 ECEF 四元数。10 组独立 Java 参考直接调用正式 AMASE JAR，覆盖北／东／南／西、正负俯仰、左右滚转和混合姿态。

| 校准 | 本轮结果 |
| --- | --- |
| 85 个独立 PROJ／WGS84 ECEF 点，含负高度及跨边界邻近点 | 最大误差 2.134×10⁻⁹ 米 |
| 同点 EGM96 改正 | 最大差 5.330×10⁻¹⁴ 米 |
| 10 组正式 AMASE 姿态 | 最大夹角 1.208×10⁻⁶ 度 |
| 选用 GLB 顶点／法线／UV 转换 | 最大数值差 2.981×10⁻⁸ |
| 两模式真实 WS 回放与显示位置 | 最大误差 1.614×10⁻⁹ 米 |
| 6 个暂停模型的真实渲染矩阵与实体四元数复核 | 最大列向量差 3.331×10⁻¹⁶ |

以上为数值转换误差，**不是原 DEM、EGM96 或实体定位的绝对精度**。独立测试另覆盖五类拒绝及六类插值边界，包括超安全整数时间、单样本、无样本、端点夹取及 359°→1° 短弧。

显示目标由后端仿真时间减 1000 ms 得到，夹在实际已接收样本区间；位置 ECEF 线性插值、姿态四元数短弧插值，不按浏览器墙钟外推。暂停立即保持显示时间，底部仍显示权威后端时间，详情同时标明源状态和显示时间。当前约 1.88 Hz 源消息下显示按消息更新；本卡未宣称达到 30 FPS 平滑运动资格。

轨迹沿用 T05 最近 10 分钟、每实体最多 2048 个源样本，可另加当前插值端点；初始／刷新快照不伪造历史。新流、断线、删除清除对象和选中／跟随引用，任务完成保留实体。九项独立实体生命周期检查通过；完整观察恢复／网关重启矩阵继续归 T08。

## 4. 真实浏览器及运行验证

中文候选在 Headless／Gui 后端分别运行 T04 三实体地形副本及正式 G4。三实体均由真实快照／连续增量绘制，GLB 与纹理实际加载；源正高 1090 米转换后约 1069.84 米。每模式在运行、移动、暂停和刷新后，独立重放浏览器收到的真实帧，对照状态和插值上下界；没有发送浏览器控制包。两模式分别暂停于 10609／10039 ms，每实体取得 10 个样本；等待期间显示时间、位置、姿态和底部时间保持。

选择／详情、定位／跟随／复位、三类图层开关、倍率上下界及复位通过。刷新期间实体层先释放，再由原地图销毁 Viewer；刷新后只显示新快照位置、零历史轨迹。关闭网关后显示恢复状态，实体及跟随清空，后台保持正常。AMASE／UxAS、网关、Edge 及 Node 服务全部正常退出，端口释放。

实际 Edge **153.0.4234.48** 报告 **ANGLE／NVIDIA RTX 4000 SFF Ada／D3D11**；这是浏览器实际 renderer，非据硬件名推断。引擎统计每模型纹理 87381 字节（含 mipmap），不等于全部显存／进程内存。真实运行与暂停截图位于本轮每模式 browser 目录，已检查模型和页面显示。FPS、完整资源峰值和 20 实体稳定性留待 T10。

重构建的组合包另通过原 T03 离线地图探针：中文标签、地形／接缝、卫星失败回退、全局浏览、刷新和浏览器退出；HTTP 四类 Range、24 并发、六类范围拒绝、65 个公共边界节点及有界缓存检查通过。生产 8080 冲突明确失败，既有服务保持。客户端不完整 HTTP 重置未终止资源服务。

普通候选从 `out/tmp/G5 T06 中文入口` 启动联合会话，省略 BaselineRunId 重新检查后端；实际代理 health ready、三实体快照和 GLB 字节摘要正确。创建本次 request-stop 后正常退出。本卡日常入口只验证启动与提前收尾，不重复宣称完成 T09／T10 全程；自动等待三任务完成后暂停分支继续沿用 T05，未另作完整显示验收。

模型反例 `g5-t06-model-rejection-20260921-102900`：无效 OSGB 明确返回 1；候选所用文件校验函数对隔离的缺失／损坏 GLB 拒绝，原件和合格包不变。工具只读复查成功。两类路径候选的 405 个生产文件完全相同。

## 5. 入口、失败记录与交接

在仓库根目录执行：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
# 工具已在本轮构建；以后先复查，来源变化才重新构建。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-g5-models.ps1 -PythonExecutable $pythonExe -VerifyOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\build-g5-entities.ps1 -PythonExecutable $pythonExe -ChinesePath
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g5-entities.tests.ps1 -PythonExecutable $pythonExe -BuildRunId '<本次构建编号>'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\start-g5-entities-session.ps1 -PythonExecutable $pythonExe -BuildRunId g5-t06-build-20260921-102716-695 -Mode Gui
```

日常入口不自动打开浏览器；收到 session-ready 后访问 `http://127.0.0.1:8080`。8080／8000 和后端端口沿用 T05；创建 `out/runs/<本次 session 编号>/request-stop` 正常关闭所属进程。入口可从其他工作目录调用，参数必须绑定实际合格候选。源／数据／工具摘要不符则停止，禁止重写旧清单。

过程失败均保留：初次 OSG 编译因 E 盘已满中断，用户释放空间后重建成功；当时只读检查后剩余约 1.41 TB，不将清理后的目录大小当作清理前增长归因。首次探针还修正了 PowerShell 原生命令 stderr 警告处理。前端调试依次修正字体目标目录已存在、Cesium pack 缺少输出数组、TypeScript 7 显式文件编译需 ignoreConfig／NodeNext 扩展名等入口问题。真实失败批次 g5-t06-test-20260921-102213-967 在刷新时暴露 Viewer 提前销毁后的访问；修复 beforeunload 清理顺序和重复清理保护后，用新候选完整复验通过，不覆盖失败记录。

只登记 `entityDisplayQualified=true`、`stageQualified=false`。T07 下一步消费此实体／高度配置，绘制完整航线、任务及区域；T08 做完整恢复，T09／T10 做原两实体／20 实体全程，T11 绑定本轮页面人工确认、正常退出和正式发布。模型原件、后端及地图数据均未改动。
