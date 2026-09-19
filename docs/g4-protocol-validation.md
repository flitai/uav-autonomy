# G4-T02 协议核心与真实接入验收

日期：2026-09-19，Asia/Shanghai。**T02 已完成；T03 状态模型与记录可执行。** 本卡验证新协议核心和两路只读接收，不代表浏览器、自动恢复或完整任务通过。

## 交付与运行

`src/sim_bridge` 是框架无关核心，按七份固定 MDM 预检 LMCP 字节布局、数组、嵌套、有限数值及地理范围，再调用同批生成类检查消费长度。Sentinel 长度与实际校验、属性／内部类型一致及内部 LMCP 校验均严格执行；未知类型、无效数据或 EOF 残包不会进入业务状态。对外 int64 从字节解码起即转换为十进制字符串。

TCP 接收和记录分别在独立线程工作，队列上限 64 个 64KiB 块，诊断历史最多 64 条；原始字节及逐帧字段／偏移／来源／摘要写盘。慢消费者满队列时关闭自己的观察连接并留下故障，不无界扩容；每个新连接使用独立解析状态。接收器不发送业务消息。

独立编排复用未修改的 G3 受控启动，额外旁路接收 AMASE 和 UxAS；逐帧与原 G3 独立观察结果核对，确认两实体真实动态数据、SessionStatus、规划响应及实际命令。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
# 仓库根目录；省略 BaselineRunId 时重新执行来源资格检查。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g4-protocol.tests.ps1 -PythonExecutable $pythonExe
# 单模式取样：
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\run-g4-protocol.ps1 -PythonExecutable $pythonExe -Mode Headless
```

每次产生独立 g4-t02- 编号，不覆盖旧证据；两模式顺序运行，端口沿用 G3 配置并核对本次所有者。GUI 自动正常关闭，此短程入口不代替 T09 的本轮人工确认。

## 实际验收

最终运行 `g4-t02-test-20260919-230412-248` 的 result／entry-result 均 passed，两模式均正常退出并释放端口。首次 `g4-t02-test-20260919-230151-562` 也通过；最终复验在额外队列／真实 socket 检查加入后进行，旧记录保持。

| 检查 | 结果 |
| --- | --- |
| 历史全量对照 | G3-T07 AMASE 5451 帧、UxAS 观察口 6821 帧全部严格解码，164 类型模型注册齐全 |
| 分帧 | 状态样本 384 处切分、命令样本 339 处切分、粘包及 EOF 残包检查通过 |
| 无效输入 | 25 项坏长度／校验、类型／属性、未知根类型、NaN／Inf／越界坐标及未配置实体拒绝 |
| 数字精度 | `2^63-1` 实体 ID、`2^53+1` 时间完整保存为字符串 |
| 真实局部网络故障 | 分包、半帧 EOF、坏校验、慢消费者均用实际本机 TCP；满队列峰值精确达到 64 后拒绝，保留 Full 与尾部 |
| 真实系统 | GUI／无界面两个真实实体各不少于 10 条递增且移动的状态；两路每条已接收消息摘要均存在于独立观察记录 |
| 命令与来源 | AMASE 0／0 来源与 payload 身份分离；UxAS 观察源白名单；规划、命令及 SessionStatus 齐全，网关发送业务帧数为 0 |
| 生命周期 | 两模式正常退出、接收线程结束、合法运行尾部为空、所有本次监听端口释放 |

原始证据在每模式 g4-amase／g4-uxas 子目录，包括 raw.bin、messages.jsonl、tail.bin 和 summary.json；gateway-ingress.json 保存对照结论，protocol-checks／transport-checks 保存反例和上层预期拒绝。局部故障接收记录保留 error，不改成正常接收。

## 问题与边界

首次预检遗漏 MDM byte 基元，按现有生成器的实际 B 编码补齐后全量历史重放通过；char 同步使用 c 编码。没有修改模板或生成代码。当前业务字符串仍只支持 ASCII；大型图数组另受网关资源上限约束，不将全部注册类型等同于全部业务场景联调通过。

T02 尚无在线重连、快照或规范化对象生命周期；主任务仍由 G3 编排执行，短程在取得真实规划和动态样本后关闭。下一卡实现状态归约、持久记录及按当前日志提交边界重建。
