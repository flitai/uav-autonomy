# G4 浏览器协议 v1

本契约属于 [G4 方案](g4-message-gateway-plan.md)。接口实现／验收以当前任务状态为准，依赖冒烟不代表真实网关通过。

## 运行身份与状态

浏览器只读访问本机网关。`schema_version=1`；运行编排生成 `run_id`，绑定本次后端 PID、创建时间、配置及来源；网关每次重建发布流生成 `stream_id`。序号 `sequence` 为十进制字符串，作用域为该流。客户端看到新运行或新流时清空旧状态和插值样本。

健康状态为 `initializing`、`live`、`recovering`、`degraded`、`ended`。`ready=true` 仅表示本次身份、两路连接、初始状态和日志补齐均合格；HTTP 能应答本身不表示 ready。断流保留最后状态并明确过期，不继续虚构仿真时间。

## HTTP 与 WebSocket

`GET /api/v1/health` 返回运行身份、状态、ready、连接／日志健康、最后错误及墙钟。`GET /api/v1/snapshot` 返回快照；未具备完整快照时返回 503 和当前健康状态。`WS /api/v1/stream` 首帧为快照，随后仅发送其边界以后的增量；恢复中可发送 health，完整快照前不能发送业务增量。`/` 为无第三方在线资源依赖的诊断页。

快照包含 `schema_version`、`run_id`、`stream_id`、`sequence`、`kind=snapshot`、`state`。state 中实体、任务、命令、航线及区域均按字符串 ID 建索引；simulation 单独保存。增量包含相同头及 `kind=delta`、`changes`，每项为集合、对象 ID、`upsert`／`delete` 和新对象。一个提交产生一个序号，客户端不跨缺口继续应用，重新连接取得快照。

首次快照和其后的增量在同一同步边界登记，不能先做 HTTP 查询再无边界订阅。浏览器刷新／重连始终重新快照；v1 不承诺断点增量恢复或历史时间轴回放。WebSocket 输入只允许健康／连接协议，不能发送任务或仿真控制。

## 对象、来源与单位

| 对象 | 数据及来源 |
| --- | --- |
| entities | AMASE 的 EntityConfiguration／AirVehicleConfiguration 与真实 AirVehicleState；业务 entity_id 与外层 source_entity 分开 |
| tasks | CMASI 点／线／区域任务及 UxAS TaskInitialized／TaskActive／TaskComplete；保留对应实体和原始完成时间 |
| routes／commands | AutomationResponse 的完整计划、MissionCommand 的分段航线与 VehicleActionCommand；消息收到和状态确认执行分开 |
| zones | KeepInZone／KeepOutZone／OperatingRegion 及 RemoveZones；几何与所属 ID 保留 |
| simulation | AMASE SessionStatus 的源仿真毫秒、运行／暂停／结束、实际倍率 |

所有 int64 标识和时间（含嵌套 ID、航点、任务关联、序号）均使用字符串；不能依赖通用 JSON 编码把 Python 大整数直接交给 JavaScript。仿真时间字段使用 `simulation_time_ms`，接收墙钟为带时区的 `received_at`，不将前者解释为 UTC。经纬度字段明确 `longitude_deg`、`latitude_deg`，高度为 `altitude_m` 并保留 `altitude_reference`。姿态保留源角度，不做 Cesium 模型轴校正。

任务完成不删除任务；对象删除只由本次合法 RemoveEntities／RemoveTasks／RemoveZones 或新运行快照触发。过期只改变健康／新鲜度。对同一对象，更新保留来源及最后事件身份，禁止其他连接的重叠转发覆盖 AMASE 权威状态。

## 记录与恢复

严格解码先验证两层长度、校验和与类型。原 TCP 收包和字节缺口原样记录。关键任务／命令／生命周期以已提交 UxAS 消息日志的分片与行号排序去重；补齐使用同批生成类解码日志 XML，不把日志重新序列化结果冒充原始 TCP 字节。

恢复时先核查 run_id、后端 PID／创建时间和日志来源，按日志提交边界重建，随后新流快照接续真实增量。日志缺失、损坏、身份变化或主任务链路故障时不得恢复 live。所有队列有界，慢客户端超限后关闭并重新同步；关键事件保留在磁盘，不能因浏览器消费慢阻塞主任务。

G4 不提供任务注入、仿真控制、任意文件路径读取或浏览器历史回放接口。

## T03 对象字段与记录约定

下表为已落地状态归约的字段；HTTP／WebSocket 已由 [T04](g4-web-validation.md) 两模式真实验收，自动观察恢复仍由 T05 验收。

| 集合／键 | 主要字段 |
| --- | --- |
| entities／entity_id | configuration、state 保留规范化 LMCP 字段；position 显式经纬度／高度／基准，attitude 保留源角度；simulation_time_ms、current_command_id、current_waypoint_id、associated_task_ids |
| tasks／task_id | kind=point／line／area，definition 保留完整几何和参数，eligible_entity_ids；initialized、assignments、active、backend_completed 与 completed_entity_ids／completed_time_ms 分开 |
| routes／entity_id | planned_mission 为当前完整规划，含航点、关联任务、动作、下一航点及源高度基准；不随分段命令缩短完整规划 |
| commands／entity_id:mission 或 entity_id:action | 当前 message、command_id、received；execution_observed 仅由同实体、同命令的实际状态确认；任务是否完成由 tasks 表达 |
| zones／zone_id 或 region:region_id | 原几何和参数在 definition，kind 区分 KeepInZone／KeepOutZone／OperatingRegion |
| simulation | simulation_time_ms、start_time_ms、源 State 枚举和 real_time_multiple；不通过墙钟自行外推 |

对象 source 保存来源实体／服务／组、已提交日志 event_id（shard、row_id）及 source_time_ms；这些字段与业务 entity_id 分开。保留的 LMCP 字段沿用原 PascalCase，嵌套对象用 `_type` 标明类型；int64／uint64 已递归转换为字符串，枚举保留模型整数值。TaskAssignment 的预测时间属于规划，不作为真实 TaskComplete。

状态重建以本次日志提交顺序为准，重复分片／行号不重复应用，持久记录还必须摘要一致。实体源时间回退不覆盖较新状态；删除墓碑保留到本次运行结束，不接受相同运行内旧配置或迟到状态将对象复活。G4 固定场景若需重新使用已删除 ID，须新运行；动态重置／场景切换归 G6。当前集合和墓碑各限 4096 项，命令每实体每类只保留当前对象，全部事件另在磁盘持久保留。

## T05 恢复状态字段

以下字段已实现，完整验收进度见 [恢复报告](g4-recovery-validation.md)，不据此声明阶段完成。

health 的 `recovery` 包含 `active`、当前日志 `cursor`、连接 `epoch`、完成补齐次数 `completed` 及明确的提交 `boundary`；分片、行号和次数为十进制字符串。`wire_gaps_preserved=true` 表示原始缺口保留，不能解释为收包已经无损补回。重建期间的 cursor 表示处理进度，只有 ready 的新流快照才可用作浏览器完整状态。

`freshness` 包含 `paused`、各观察源最后收包距今的 `source_ages_seconds` 和 `stale`。这里的秒数是本机单调时钟间隔，不是后端仿真时间。运行中超过 5 秒没有新数据时暂停完整快照；本次日志确认暂停时允许静默，但进程、主链路、观察连接及日志完整性仍须合格。过期不删除对象，不修改任务完成状态。

观察故障关闭旧流；已连接客户端收到关闭码 1013 后重新连接。尚未恢复时，WebSocket 可以只发送 health 后以 1013 关闭，不能把它当作业务快照。恢复完成后新连接首个业务包必须为新 stream_id 的 snapshot；浏览器须清理旧流数据，再连续应用其后的 delta。普通刷新也从新快照开始。

同一后端运行的持久事件库跨网关进程保留。重新启动必须使用同一运行清单，核查 PID／创建时间、主任务连接、日志文件身份／首行摘要及既有事件内容。后端退出、主任务连接变化、日志缺失或损坏进入 degraded，snapshot 返回 503，必须由独立编排创建新后端运行；浏览器及网关均无权继续旧任务或自动重发请求。
