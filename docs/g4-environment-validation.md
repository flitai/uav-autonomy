# G4-T01 输入、环境与契约验收

日期：2026-09-19，Asia/Shanghai。**T01 已通过；真实 TCP 网关接入仍待 T02。** 本卡未启动 AMASE／UxAS 仿真，HTTP／WebSocket 是独立依赖冒烟。

## 交付与入口

- 配置：G4 基线绑定 G3-T07 handoff；Python 完整依赖锁包含官方 wheel URL、版本及 SHA-256，安装要求哈希且禁用额外依赖解析；网关默认本机 8000，队列、解析及重连参数显式登记。
- 环境：每次构建新 `.tools/g4/environments/<run-id>`，验证成功后原子切换 `.tools/g4/current.json`；记录运行库安装文件摘要，VerifyOnly 不安装或下载。
- [浏览器契约](g4-browser-contract.md)：版本、运行／流身份、同连接快照与增量、int64 字符串、来源、时间、删除、过期和日志语义补齐。

从任意工作目录以绝对脚本路径调用；以下相对命令在仓库根目录运行：

```powershell
$pythonExe = Join-Path $env:LOCALAPPDATA 'Python/pythoncore-3.14-64/python.exe'
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-g4.ps1 -PythonExecutable $pythonExe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\windows\setup-g4.ps1 -PythonExecutable $pythonExe -VerifyOnly
# 用本次 passed 的 G3 资格编号替换占位符。
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tests\windows\g4-environment.tests.ps1 -PythonExecutable $pythonExe -BaselineRunId '<G3_BASELINE_RUN_ID>'
```

省略 BaselineRunId 时重新执行既有正式资格入口；提供编号时仍复查输入、正式文件与 handoff。重复 RunId 拒绝，不覆盖历史。环境使用 base Python 3.14.7 x64，运行脚本加 `-I -B -X utf8`，不更改全局安装、持久 PATH 或执行策略。

## 本轮证据

| 项目 | 结果 |
| --- | --- |
| 当前来源资格 | `g3-t01-check-20260919-224451-856` passed，正式 AMASE／UxAS／CRT、Java／Ant、同批 LMCP 与 43 项冻结输入 |
| 环境构建／冒烟 | `g4-t01-20260919-224933-026` 的 result／entry-result passed，安装 14 个固定 wheel，pip check 通过 |
| 入口与路径矩阵 | `g4-t01-checks-20260919-225116` acceptance passed；中文空格且不同工作目录复验、重复编号拒绝／历史保护、缺解释器拒绝 |
| 依赖／来源反例 | 错 handoff 摘要和错误依赖摘要拒绝；不修改正式文件／旧收据 |
| HTTP／WebSocket | 本机测试专用临时端口上真实 HTTP 请求、WS 双向 JSON、int64 字符串、正常服务关闭及端口释放 |
| 环境影响 | 当前入口进程环境及工作目录未改变；所有服务仅本轮测试所有，未启动仿真 |

主要版本为 FastAPI 0.141.1、Uvicorn 0.53.0、Pydantic 2.13.5／pydantic_core 2.46.5、websockets 17.1、Starlette 1.6.0；全部 14 项以 `config/g4-python-lock.json` 为准。pip 解析只允许可用 wheel，实际安装从已核对 wheel 缓存执行 `--no-index --no-deps --require-hashes`。

测试临时端口由测试显式绑定后传给服务器，不属于生产端口回退。生产端口 8000 的冲突必须明确失败。旧环境指针仅在完整安装和冒烟通过后替换。

## 限制与下一步

未验证真实网关、状态归约、在线日志补齐或混合任务；这些分别归 T02～T08。现有 G3 日志内容可作为补齐输入，不等于已证明在线锁竞争、日志断流或恢复一致性。T02 按 [阶段方案](g4-message-gateway-plan.md) 建设有界严格协议核心并与真实两端消息对照。
