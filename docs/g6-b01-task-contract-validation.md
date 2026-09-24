# G6-B01 首批任务契约与真实输入基线

日期：2026-09-24。状态：B01 输入基线通过，B02 可进入实施；尚未开放任务写接口、规划预览或执行下发。独立收据为 `out/runs/g6-b01-baseline-20260924-2223/acceptance.json`，`inputBaselineQualified=true`、`executionQualified=false`。历史初跑 `g6-b01-baseline-20260924-2222` 通过原始核对；补充规划服务链源码断言后用新编号重新验收，旧记录保留。

## 1. 来源和实际输入

B01 通过 `out/artifacts/g6-control/current.json` 解析 G6-A 正式增量，再绑定生产入口 `g6-control-production-check-20260924-2215` 的成功收据、运行哈希与首段真实场景。验收脚本逐个复查 `scene.json` 登记的上游文件与场景文件哈希，解析 `CMASI.xml`、`UXTASK.xml` 及三个现行 UxAS 服务源文件；没有启动 UxAS，也没有发送业务消息。当前场景为 `g5-terrain-small-usgs-egm96-v1`，任务地面高度为 EPSG:5773 正高，LMCP `AltitudeType=MSL`，G5 真实地形资格范围为西经 122～120、北纬 45～46 度。客户端坐标统一采用 `[经度, 纬度]`；海拔由服务端从同源地形取得，首批草稿不允许直接编辑高度。

| 模板 | 真实任务／实体 | 实际任务输入 | 首批候选限制 |
| --- | --- | --- | --- |
| 线搜索 | `LineSearchTask` 3000／实体 400 | 完整水道 90 个点；原 90 点未简化 | 折线 2～128 点、无连续重复点；首批固定 400 |
| 点搜索 | `PointSearchTask` 3001／实体 500 | 搜索位置、`StandoffDistance=0` | 一个地面点；首批固定 500 |
| 矩形区域 | `AreaSearchTask` 3002／实体 600 | 矩形中心、1000 × 500 米、旋转 0° | 宽／高各 100～2000 米，完整矩形留在资格范围；首批旋转 0°、固定 600 |

三类真实 XML 均为 `DwellTime=0`、`GroundSampleDistance=1000` 米／像素、`RevisitRate=0` 秒、`DesiredWavelengthBands=AllAny`、空视角列表、`Priority=0`、`Required=true`；请求为固定一机一任务、`OperatingRegion=0`、空 `TaskRelationships`、`RedoAllTasks=false`。实体 400／500／600 在真实场景中均有配置、状态、相机和云台。G6-B04 仅沿用这些已验证参数及固定分配；B05 才验证多机竞争和任务排序。首批最多 3 个草稿、单次请求最多 64 KiB；这些新接口预算为 B02／B03 待实测上限，不能写成 UxAS 性能结论。

机器可读冻结契约在 [g6-task-contract-v1.json](../config/g6-task-contract-v1.json)，真实来源导出的草稿样本及预览／确认设计样本在 `out/runs/g6-b01-baseline-20260924-2223/samples/`。后两者明确标记 `illustrative-contract-only`，不是已运行的 UxAS 规划结果。B01 实际拒绝了非零 DwellTime、错误实体、颠倒经纬度、重复线点、越界矩形、额外高度字段和数值型任务 ID 七种输入；不把未覆盖的错误类型宣称已验收。

## 2. 前后端身份和状态契约

新增业务 API 版本为 `g6.tasks.v1`，本机写入口继续要求当前 Cesium 页面来源。所有写请求带 `runId`、`segmentId`、后端 `backendRunId`、观察 `streamId`、草稿／计划修订号和幂等键；LMCP `int64` 标识及仿真毫秒在 JSON 中使用十进制字符串。旧分段、旧流、版本冲突和身份不符均拒绝。草稿状态为 `draft → preview_pending → previewed → confirmed → executing → completed`；输入变更或重置使已有预览进入 `stale`。操作状态为 `pending/confirmed/rejected/uncertain`，丢响应先用幂等键查询，结果不明时阻止冲突确认和自动重发。

预定路由为 `GET/POST /api/tasks/v1/drafts`、`POST /api/tasks/v1/previews`、`GET /api/tasks/v1/plans/{planId}`、`POST /api/tasks/v1/plans/{planId}/confirm` 和 `GET /api/tasks/v1/operations/{key}`。B01 只冻结请求／结果形状，路由尚未实现。草稿保存不发送 LMCP；预览输入摘要包含任务修订、实体配置与状态事件 ID、地形 manifest 哈希和规划配置哈希。计划保留唯一版本、完整输入摘要、原始规划响应摘要和生成时仿真时间；暂定 30 仿真秒有效，任何输入／实体状态变化优先令其失效。B04 必须用审查时同一方案字节下发，确认时不得重新计算另一份方案。

| 条件 | 预定反馈 | 写入口处理 |
| --- | --- | --- |
| 非法几何／字段／高度基准 | `invalid_input`，HTTP 422 | 无规划消息 |
| 未合格实体、任务类型或参数 | `unqualified_input`，HTTP 422 | 无规划消息 |
| 旧运行／分段／流或修订 | `stale_identity`／`version_conflict`，HTTP 409 | 不覆盖新草稿或方案 |
| 已过期／输入改变的方案 | `plan_stale`，HTTP 409 | 不下发；需重新预览 |
| 无可行解 | `no_feasible_plan`，HTTP 422，保留 UxAS 原因 | 不生成可确认方案 |
| 规划超时、后端失联 | `planning_timeout`，HTTP 504／`backend_unavailable`，HTTP 503 | 记录结果；不把未知状态当失败重试 |
| 确认结果不明 | `result_uncertain`，HTTP 202／查询接口 | 阻止冲突操作，先查实际后端状态 |

首批固定分配不开放任意 `TaskRelationships` 或 `RedoAllTasks`。删除草稿只删除尚未执行的业务输入；已下发任务不能靠删除草稿停飞。重置淘汰旧草稿预览和方案；执行中修订、取消和替换归 B06。统计以 `taskId + taskRevision + runId/segmentId` 关联：任务几何、DwellTime、GSD 或资格参数变化必须新统计版本，旧覆盖不混入；未变任务能否继承统计只在 B06 通过实测复算后开放，首批默认不继承。

## 3. 预览隔离与下一卡门槛

源码确认：CMASI `AutomationRequest` 声明新请求取代旧请求；`AutomationRequestValidatorService` 可将 `TaskAutomationRequest` 包装为带 `SandBoxRequest` 的 `UniqueAutomationRequest` 并返回 `TaskAutomationResponse`；`PlanBuilderService` 发出 `UniqueAutomationResponse`；`WaypointPlanManagerService` 订阅普通 `AutomationResponse` 并据此建立／发送分段 `MissionCommand`。这些是源码事实，**不是当前预览安全已运行的证据**。

B02 必须在隔离规划实例或经真实验证的等效门控中提交三类任务预览，保留请求 ID 与响应 ID、原始消息及超时记录；活动执行后端、AMASE 命令口和实体动作在预览期间必须零新增命令。仅设置 `SandBoxRequest=true` 不足以替代该验证。若返回普通 `AutomationResponse`、出现航点或传感器动作、串号或预览覆盖活动请求，写入口拒绝发布；G6-A 及 G5 原入口不受影响。B03 才接入地图绘制，B04 才验证方案确认与真实执行。

复验入口：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $pythonExe -I -B -X utf8 scripts/g6_tasks/baseline.py --run-id 'g6-b01-<NEW_ID>'
```

入口先复查正式 G6-A／G5 来源，失败保留本次 `result.json`，不更改正式指针或活动任务。
