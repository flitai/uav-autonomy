# G6-B02 规划预览隔离验收

日期：2026-09-24。状态：B02 已通过；B03 任务编辑与草稿为下一卡。正式 G6-A 及 G5 指针未改变。B02 开放的只有运行本地预览服务；确认下发与执行入口尚未实现，`executionQualified=false`。

## 实际实现与隔离边界

- `apps/g6_tasks/server.py` 提供独立的 `127.0.0.1:8002` 业务接口：`GET /api/tasks/v1/state`、`POST /api/tasks/v1/previews`、`GET /api/tasks/v1/plans/{planId}` 和 `GET /api/tasks/v1/operations/{key}`。写入要求本地页面 Origin、严格字段、64 KiB 限额、运行／分段／后端／流身份、草稿修订及幂等键。服务不提供确认下发路由。
- `scripts/g6_planning/task_input.py` 从 B01 合格草稿生成点／线／矩形 LMCP 任务，继续固定任务 ID 与一机一任务；新几何的 MSL 地面高度从 G5 已核验的 `orthometric.f32` 正高网格按同源双线性公式计算。网格、地形候选、G6-A 正式指针和生产场景哈希在使用前复查。
- 每次预览由 `isolated_preview.py` 启动独立 UxAS 进程，只有 `127.0.0.1:10031` 的本地观察／注入桥；配置移除活动 AMASE 桥、观察桥及 `WaypointPlanManagerService`。保留 `SensorManagerService` 以完成矩形任务的传感器覆盖计算。隔离实例接收真实实体配置／初始状态、任务和 `SandBoxRequest=true` 的 `TaskAutomationRequest`，以请求／响应 ID 一一对应。候选内必须有指定实体、任务关联及至少两个航点，错误 Info 或空方案拒绝。原始注入帧、观察帧、完整预览 XML、方案哈希和可查看航线均单独留存。
- B02 当前仅允许**活动运行已就绪但尚未点击开始**的冻结初始状态。服务逐次核对 AMASE、UxAS 进程和 G4 流身份；预览前后核对活动观察流中无新增 AutomationRequest／Response、TaskAutomationRequest／Response、MissionCommand 或 VehicleActionCommand，也要求没有实体运动状态。活动执行期间或状态不明时拒绝本卡预览；从动态状态规划属于后续受控重规划资格。

本地组合入口，工作目录为仓库根目录：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $pythonExe -I -B -X utf8 scripts/g6_planning/api_probe.py --run-id 'g6-b02-<NEW_ID>'
```

接口服务由组合入口在活动 G6-A 会话内启动并在结束时关闭。B03 接入页面前仍需从合格本地会话取得 `control-session.json`，不能拿历史退出运行的文件启动可用服务。

## 实际验收

当前源码收据：`out/runs/g6-b02-acceptance-20260924-2410/acceptance.json`，`status=passed`、`previewIsolationQualified=true`、`executionQualified=false`；收据绑定 B02 五个源码／契约输入哈希。Headless 与 Gui 两模式各有独立活动 AMASE、UxAS、G4、G6-A 控制进程和独立预览服务。两模式各自通过真实 HTTP 请求取得三份方案：线 73、点 14、矩形 5 个航点，原始 `TaskAutomationResponse` 和对应的完整方案 XML 均保存。活动观察流在三次预览前后没有新增规划请求或执行命令，活动 UxAS 进程身份和网关流身份保持相同。两模式活动会话均正常退出，端口 5555／9999／8000／8001／8002／10031 全部释放。

每个正例另核对重复幂等请求返回同一收据、按 planId 查询同一方案。HTTP 拒绝同键异文、越界／颠倒经纬度、旧 streamId、无 Origin，并确认未资格化的 `/confirm` 返回 404。隔离规划器的三条独立反例分别拒绝未知任务类型、错误响应 ID 和缺少请求校验服务导致的 30 秒规划超时；三条失败收据与正常清理证据保留在同一验收目录及其对应运行目录。

初始隔离探针 `g6-b02-isolated-probe-20260924-2235` 曾把矩形任务的无可行信息误记为成功；矩形的 `SensorManagerService` 被误删，且当时只检查响应 ID。修正后 `g6-b02-isolated-probe-20260924-2240` 开始验证非空航线。API 联测 2315、2321、2324、2327 各轮因初始状态判断或导入路径等编排错误失败，原始收据保留；2331、2343、2351 后续通过，2400 收据通过完整拒绝矩阵。最后修正任务高度网格在闭区间边界的采样，按新源码重跑 2410 收据作为当前资格。旧失败不改写成通过。

B03 要将此业务接口接入地图草稿工作流，验证真实绘制、修改、保存、刷新恢复和服务端输入一致性。B04 才可设计并验证“审查同一方案后确认下发”；仅有当前预览方案与 `SandBoxRequest` 不构成执行许可。
