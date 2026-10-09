# G6-B07 生命周期与故障恢复验收

日期：2026-10-09，Windows 11 x64，Asia/Shanghai。结论：**G6-B07 独立候选通过**。最终源码构建 `g6-b07-build-20261009-09/result.json` 与汇总 `g6-b07-acceptance-20261009-final/acceptance.json` 均为 passed，汇总 `lifecycleQualified=true`；下一卡为 B08 组合验收与阶段交接。G5／G6-A 正式指针没有切换。

## 实现与边界

B07 在已验收的 B06 受控重规划上叠加按运行段保存的操作账本。规划请求先持久化 `pending`，经活动状态和隔离规划核对后才标为 `previewed`；取消、超过期限、服务重启或流身份变化会阻止迟到结果成为可确认方案。确认切换沿用 B06 的逐步操作收据；服务在确认途中重启时标为 `uncertain`，不自动重发任何任务或命令。每段最多保留 8 个规划操作，写入限制为本机业务页面来源、64 KiB JSON 及现有身份／幂等键规则。

页面在右侧任务工作区新增收起的“操作与恢复”。它查询操作状态；刷新或任务服务重启后，可从持久方案恢复审查，再由用户核对并明确确认。失去后端／网关身份时页面只读；网关恢复并改变流身份后，旧预览记为 `stale`，可以从新流重新规划。`/api/tasks/v4/state`、`/operations/{key}`、`/operations/{key}/cancel`、`/history/{segment}/{key}` 提供当前及旧段查询；原 B06 `/api/tasks/v3` 规划／确认入口保持。

## 真实运行证据

| 验证 | 结果 |
| --- | --- |
| Headless 执行中修订 | `g6-b07-session-headless-20261009-final`、`g6-b07-flow-headless-20261009-final` 与独立审计 `g6-b07-audit-headless-20261009-final` passed。新任务 3100／3101／3102 完成，AMASE 收到 400 的 30／30 和 500 的 14／14 个新航点；切换后旧任务完成与旧关联动作均为 0，新关联动作 95 条。旧新覆盖按事件账本复算一致。受控重启任务服务后 PID 改变，同键操作仍可查为 `confirmed`；会话正常退出。 |
| Gui＋真实 Edge 刷新 | `g6-b07-session-gui-20261009-final`、`g6-b07-browser-gui-20261009-final` 与独立审计 `g6-b07-audit-gui-20261009-final` passed。预览后刷新页面，从“操作与恢复”取回相同 SHA256 的审查，第二请求端争用被 HTTP 409 拒绝；明确确认后 3100→3101→3102 完成，400 的 43／43 个航点被 AMASE 接收，旧完成／关联动作均为 0，新关联动作 117 条，覆盖复算一致。`review.png`、`completed.png` 与正常退出已留存。 |
| 取消、超时、重置 | `g6-b07-session-faults-20261009-final` 两段均正常退出，`g6-b07-faults-20261009-final` passed。取消与本次 2 秒期限的规划结果后来均返回 `previewed`，账本分别保持 `canceled`、`timed-out`，未产生新活动命令。相同幂等键重放只返回原结果，不同请求体被拒绝。重置后新段身份和空账本成立，旧段历史可查且旧写入被拒绝；超大 int64 字符串与不安全 JSON 数字任务 ID 未留下操作记录。 |
| 网关重启与跨运行 | `g6-b07-session-gateway-20261009-final`、`g6-b07-gateway-20261009-final` passed。所属网关正常停止后 B07 只读，重启得到新观察流；旧预览记为 `stale`，旧审查／确认被拒绝，新流重新预览成功，活动命令仍为原 7 条。另一运行的身份被 HTTP 409 拒绝且没有占用本段操作键。`g6-b07-origin-20261009-final` 证明观察和回放来源写入均为 HTTP 403。 |
| 后端退出与账本恢复 | 故障会话 `g6-b07-session-backend-20261009-01` 受控结束本次 UxAS 后按预期 failed；独立 `backend-exit.json` 记 B07 只读、规划 HTTP 409，所属资源已清理。`g6-b07-ledger-20261009-final` passed：未完成规划重启后为 `interrupted`，确认／切换待决为 `uncertain`，重复恢复稳定；第 9 个操作被拒绝且不落盘。 |

汇总脚本再次比对 B07 构建的全部输入 SHA256、四组正向会话、负例、真实 Edge 截图、两模式独立命令／覆盖审计，以及 18 个固定端口释放。没有把受控后端退出的预期失败写成正常退出，也没有把旧失败批次改写为成功。

## 历史诊断与限制

早期候选对开始前网关 `ready` 状态判断过严，已改用控制／网关身份和流核对；一次任务服务重启标记在等待中被重复处理，改为先移除标记；重置新段初始化时仍检查上段已结束的任务服务进程，现于段切换边界清理旧引用。相关失败运行、故障收据和原始日志保留在 `out/runs/g6-b07-*`，最终资格只绑定构建 09 和上述通过批次。

本卡沿用 B06 每段一次切换、旧任务须已激活且未完成的范围。规划期限在隔离子进程结束时结算，取消和超时都阻止迟到结果提升，但不强行中断正在运行的隔离规划；其原有 100 秒进程上限仍有效。后端退出必须以新运行恢复，切换结果不确定时需要核对活动后端与收据，不能重试旧命令。B08 还需完成整个 G6-B 组合验收、本轮页面人工确认和阶段发布。

## 重跑入口

在仓库根目录使用项目 Python 3.14.7 x64，每次换新运行编号；会话启动后另开终端执行探针，最后在会话目录创建 `request-stop` 并检查 `runtime-result.json`。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $pythonExe -I -B -X utf8 scripts/g6_lifecycle/build_viewer.py --run-id '<NEW_B07_BUILD_ID>'
& $pythonExe -I -B -X utf8 scripts/g6_lifecycle/session.py --run-id '<NEW_B07_SESSION_ID>' --viewer-build g6-a03-build-20260924-2330 --draft-build g6-b03-build-20260924-2438 --execution-build g6-b04-build-20260928-duration02 --assignment-build g6-b05-build-20260930-05 --replanning-build g6-b06-build-20261004-09 --lifecycle-build '<NEW_B07_BUILD_ID>' --mode Headless
```

正常用户操作将 `--mode` 改为 `Gui`，浏览 `http://127.0.0.1:8080/`。真实 Edge 刷新验收使用 `.tools/g4/current.json` 指向的独立 Python 运行 `tests/g6_lifecycle/browser.py`；Headless 修订沿用 `tests/g6_replanning/flow.py` 和 `audit.py`。取消／重置、网关、来源、账本、后端负例及最终汇总分别见 `tests/g6_lifecycle/` 的同名脚本；汇总收据列出全部绑定编号和端口检查。
