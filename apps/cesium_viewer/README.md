# Cesium 显示工程

G5-T03 实现本地 PMTiles 矢量底图、USGS 区域真实地形、可切换的 Esri 卫星影像及中文地图操作。后端消息与实体显示分别归 T05／T06；页面底部的时间仍为未连接。

使用 `scripts/windows/build-g5-map.ps1 -PythonExecutable <已核查解释器>` 构建，再以返回的编号运行 `tests/windows/g5-map.tests.ps1 -PythonExecutable <已核查解释器> -BuildRunId <本次构建编号>`。入口自行解析仓库位置、复查正式后端／G4、工具和 T02 同批地形候选与收据；构建在 `out/build/g5-map/` 副本完成，可加 `-ChinesePath`。使用隔离的 Node 与离线 npm 缓存，不修改持久环境或源目录依赖。

Node／npm 与前端依赖沿用 T01 的锁定版本。Cesium 的 Workers、ThirdParty、Assets、Widgets 全部本地部署，Noto CJK 字体和 OFL 许可按 `config/g5-map.json` 中固定的官方提交与摘要复制进候选。原始模型只读保留在 models/，转换及资源发布接入归 T06。

通过 `scripts/windows/run-g5-map.ps1 -PythonExecutable <已核查解释器> -BuildRunId <本次构建编号>` 启动生产候选，默认回环 8080；加 `-Development` 使用同一个资源服务与 Vite 中间件，严格监听 5173。创建入口输出的 `request-stop` 正常退出所属服务。端口冲突明确失败，不结束其他进程。生产运行不依赖 Vite；旧 T01 入口／收据保留历史用途。

资源服务只读：`/map/planet.pmtiles` 要求至多 4 MiB 的单段 Range，禁止整包请求；`/map/terrain/{z}/{x}/{y}.f32` 返回 65×65 北到南、低字节序 float32 椭球高；`/map/runtime.json` 明确版本、区域和限制。工作线程负责 PMTiles／MVT 解码、中文字体与矢量栅格化，Range 和目录缓存各至多 16 MiB／128 与 64 项，并发最多 4；地形服务缓存最多 64 片，前端并发最多 8。底图业务要素不作为仿真实体。

地形从 T02 的同源 EPSG:4979 高度场三角插值派生，不重复叠加地面或大地水准面改正。区域外明确返回参考椭球，属于未验收浏览范围；边界处是真实区域的裁切边缘，不向外推造地形。地图上的资格边界仅为范围提示。地形分块加密是显示采样，不提高源数据精度。Esri 按切换加载并显示服务元数据标注，失败恢复本地底图。

HTTP `/api/v1/health`、`/api/v1/snapshot` 和 WS `/api/v1/stream` 代理至回环 8000，不加入仿真控制。网关缺席返回 503，地图仍可独立浏览。T03 的代理协议夹具不是真实业务接入，后者归 T05。候选资格与地形收据绑定，正式前端指针仍由 T11 发布。

详见 [G5 方案](../../docs/g5-cesium-display-plan.md) 与 [任务卡](../../docs/backlog.md#9-g5-顺序与任务卡)。
