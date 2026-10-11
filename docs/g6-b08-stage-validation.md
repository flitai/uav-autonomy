# G6-B08 组合验收与阶段交接

日期：2026-10-11，Windows 11 x64，Asia/Shanghai。**G6-B08 组合验收、当前页面人工确认、正常退出和阶段发布已完成；G6 全阶段完成。** 候选 `g6-b08-build-20261009-02`、自动资格 `g6-b08-qualify-20261009-01`、人工确认 `g6-b08-confirm-20261011-01`、正式发布 `g6-b08-publish-20261011-01` 均通过。正式指针为 `out/artifacts/g6-stage/current.json`；G5 与 G6-A 原正式指针未切换。

## 组合包与入口

`scripts/g6_stage/manage.py` 从已验收的 B07 页面构建独立的约 40 MB 前端候选，保留 G5 正式本地矢量和地形资源的来源绑定，不复制 137 GB 全球矢量文件。候选清单逐文件记录页面 SHA256、B07 构建和验收收据、G5／G6-A 正式指针、B08 脚本来源及服务资源。`scripts/g6_stage/session.py` 在 B07 已验证的 AMASE、UxAS、网关与本地 B01～B07 服务链上使用该组合页面。运行中复查父级资格、页面文件、资源路径／大小／修改时间和地形哈希；正式发布前再完整重算全球矢量 SHA256。`check_candidate` 只返回本工作区合格候选，G8 的第二机器部署仍需单独处理绝对路径与资源打包。

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
& $pythonExe -I -B -X utf8 scripts/g6_stage/manage.py --action build --run-id '<NEW_BUILD_ID>'
& $pythonExe -I -B -X utf8 scripts/g6_stage/session.py --run-id '<NEW_SESSION_ID>' --stage-build '<NEW_BUILD_ID>' --mode Gui
# 页面 http://127.0.0.1:8080/；检查结束后创建 out/runs/<NEW_SESSION_ID>/request-stop，核对 runtime-result.json。
```

真实 Edge 浏览器组合入口是 `tests/g6_stage/browser.py`，使用项目 G4 独立环境中带 `websockets` 的 Python，`--session` 指向会话的 `segment-001/control-session.json`，`--relationship` 使用 `parallel` 或 `sequence`。`tests/g6_stage/audit.py` 对完成后的不可变网关事件账本独立重放覆盖统计，并核对页面审查、AMASE 命令与控制操作。脚本采用新输出编号，不重写历史失败收据。

## 自动复验

| 检查 | 本轮证据 |
| --- | --- |
| Headless 真实 Edge，平行分配 | `g6-b08-session-headless-20261009-02`、`g6-b08-browser-headless-20261009-06`、`g6-b08-audit-headless-20261009-02` 均 passed；三类草稿由页面保存、刷新后恢复，规划分配至 400／500，审查勾选后下发，TaskActive／TaskComplete 各一次，AMASE 收到审查航点，实际飞行。页面暂停、继续、10 倍速均产生后端已确认操作。正常退出且端口释放。 |
| Gui 真实 Edge，顺序分配 | `g6-b08-session-gui-20261009-01`、`g6-b08-browser-gui-20261009-02`、`g6-b08-audit-gui-20261009-02` 均 passed；同一页面流程，3000→3001→3002 由 400 顺序完成；正常退出且端口释放。浏览器审查和完成截图分别在对应 `out/runs` 目录。 |
| 独立统计 | Headless 网关账本游标 `1/2263`、1264 个采样状态；Gui 游标 `1/2651`、1678 个采样状态。两模式重放结果均逐字段匹配当前覆盖：线 49/49、点 1/1、矩形 375/375；点目标存在正的观察时长。没有设置最低覆盖率。 |
| 在线／离线底图 | `g6-b08-basemap-online-20261009-01` 真实 Edge 从 Esri 取得 HTTP 200 瓦片、卫星图层持续可见；两模式组合浏览器均禁止外部 DNS，自动切至本地矢量并继续完成任务。 |
| 路径／端口 | 从 `out/runs/G6-B08 中文 空格工作目录` 启动 `g6-b08-session-path-20261009-01`，正常退出并释放端口。自持排他 8080 端口时，`g6-b08-session-port-collision-20261009-02` 按预期失败，原占用套接字保持存活；收据 `g6-b08-probe-port-20261009-02/result.json`，未切换正式指针。 |

`g6-b08-qualify-20261009-01/acceptance.json` 把两模式运行、浏览器和审计收据及来源哈希绑定；该自动资格按设计仍记录 `manualReview=pending`、`stageQualified=false`，人工与发布资格由后续独立收据证明。端口冲突目前由地图服务启动失败拒绝，诊断文字仍是通用的“Service exited before ready”；原端口持有者没有被终止。首次 B08 包装会话因同名 `manage` 模块导入了 G5 模块而失败；已用独立模块名修正并重建 02。更早的浏览器试跑有确认收据查询竞态和页面就绪字段未定义，脚本改为等待后重跑；上述失败原始记录保留，不作为本轮资格。

## 人工确认与发布门槛

2026-10-09 的页面会话 `g6-b08-session-review-20261009-01` 在无人确认期间达到 8 小时运行上限，`runtime-result.json` 记录 `failed`／`timeout:whole-run`，端口已释放；没有作为人工确认收据。2026-10-11 新 GUI 会话 `g6-b08-session-review-20261011-01` 使用同一候选。用户在本轮明确回复“验收通过”；会话中真实开始和重置形成两个仿真段，随后按 `request-stop` 正常关闭。`runtime-result.json` 为 `passed`、`normalExit=true`、`segments=2`，两个段均通过并释放端口。本轮 `manual-confirmation.json` 决定为 `approve`，由 `g6-b08-confirm-20261011-01` 绑定自动资格和 GUI 退出 SHA256。PowerShell 将可选中文备注转码为不可读字符；批准决定、运行编号和哈希字段有效，原收据按发布哈希保留，不修改历史证据。

`g6-b08-publish-20261011-01/acceptance.json` 为 `passed`、`stageQualified=true`。发布前完整重算 137 GB 全球矢量的 SHA256，复制 404 个前端文件，并原子切换 G6-B08 正式指针；`manage.py --action resolve` 复核指针、包清单、逐文件 SHA256、来源和父级指针通过。独立正式包资源检查 `g6-b08-production-check-20261011-01` 从发布包的 `service.json` 启动本地服务，页面 HTTP 200、全球矢量 16 字节 Range HTTP 206（总长 137370745450）、服务正常退出；当前没有留下运行中的服务。

```powershell
# 仅在取得本轮明确批准、正常退出并核对收据后执行；每次使用新的运行编号。
& $pythonExe -I -B -X utf8 scripts/g6_stage/manage.py --action confirm --run-id '<NEW_CONFIRM_ID>' --qualification-run-id g6-b08-qualify-20261009-01 --review-session g6-b08-session-review-20261011-01 --decision approve
& $pythonExe -I -B -X utf8 scripts/g6_stage/manage.py --action publish --run-id '<NEW_PUBLISH_ID>' --qualification-run-id g6-b08-qualify-20261009-01 --review-session g6-b08-session-review-20261011-01
& $pythonExe -I -B -X utf8 scripts/g6_stage/manage.py --action resolve
```

## G7／G8 交接

G7 回放应消费本阶段的运行／段身份、网关事件游标、规划审查 SHA256、确认键、AMASE 实际命令及控制操作收据；回放观察源不得重新下发命令。G8 应将本工作区绝对路径绑定改为第二机器可解析的包接口，并复验离线矢量、区域地形、字体、前端、AMASE、UxAS 与网关的来源和正常启停。离线卫星影像包不在当前组合包内；无网络时页面自动使用本地矢量。
