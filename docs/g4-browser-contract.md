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
