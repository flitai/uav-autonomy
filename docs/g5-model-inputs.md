# G5 三维实体模型输入登记

登记日期：2026-09-20。关联 [G5-T06](backlog.md#g5-t06实体姿态与时间)。本次为用户提供的原始资源登记；T06 仍待 T05 通过，下一张实施卡仍为 T03。

## 1. 实际输入

[models/](../models/) 中有 **16 个 .osgb 文件，共 154,070,891 字节（约 154.1 MB／146.9 MiB）**，另有一个目录元数据文件 .DS_Store。原始文件只读保留；OSGB 和目录元数据加入忽略规则，转换后的候选和检查记录放入 out/，后续由前端资源发布流程纳入运行包。

本次只枚举文件、读取前 24 字节并计算完整 SHA-256，逐文件确认读取前后的长度和修改时间一致。16 个 OSGB 的前 24 字节相同：`a10e916c4545fb1a01000000830000000400000001000000`；尚未用模型读取器解码，不据扩展名或头部一致性认定几何完整、材质完整或可正常显示。原始清单见 [inventory.json](../out/runs/g5-model-input-registration-20260920-180727/inventory.json)。

| 文件（相对于 models/） | 字节数 | SHA-256 |
| --- | ---: | --- |
| ah64d_high.osgb | 55024668 | `e08128cec6a1e060fca96661c0536e2340efd96c501c65a67a9be825c4417d67` |
| aim120c.osgb | 144943 | `028574c13f7902fbe1cf895a7830c96ebf6ce7391080908cb70e0434af500ca6` |
| aim9x.osgb | 153287 | `3848e8c77a5601312e10057cdc1fbc42228a5f427846502b6cd3fb51eceb5d65` |
| bigbird_radar_high.osgb | 8490054 | `d8355465e88ff975cafef26a5c308d8b2992f0ca5e38a63c4aa621b66ad4506c` |
| bigbird_radar_icon.osgb | 207535 | `29e8db064f3c0f90a7c7bd5cde7651c4c632ff138d0b9bad4d08a8d2fa814259` |
| billboard_radar_high.osgb | 8516427 | `329a65f2f7fc4cbcfc2ca98365bb0a5ba6eefe294093c427307aff0a1aab6b8b` |
| billboard_radar_icon.osgb | 176834 | `937f90cd0d6a7e38f746e5a9c68db55c8adf8b5887d14c620efe1be883029486` |
| f16_lo.osgb | 116979 | `c5283f6385cb24c9310cd6ce5cc3af9bf3df2c806730990d3f108c658ee9a3b6` |
| f22_lo.osgb | 182113 | `e816b18e9f765fc8000ebcd2d5df7c587a1665dc0ce5e7ee90b3c79284d89446` |
| f35_lo.osgb | 127697 | `4e4125c89ec0bae98e2629b9f3a367cc907125c0f2ed293d5ec0839cdde10285` |
| gladiator_tel_high.osgb | 8606646 | `2ff2b5c726aa56eaaf0c0d6cc568e3ce2fc4171f8016d6c22cca0591783849cb` |
| gladiator_tel_icon.osgb | 207237 | `eb6afcd72ea8ed8528987f3b332895ece54c9088b2eb7deb4485a3916e9f63db` |
| j20_low.osgb | 137095 | `b3090a24a060a872982d69a6b3a1da13f915af1f850d40f4963e545699502b6a` |
| su27_lo.osgb | 141527 | `bcec9554ef46fae2265d26dbc8f9e35802874e6cd27ee1ad973cb4148e766f7f` |
| ucav_lo.osgb | 182807 | `ffb83ce6da482060a65a2eff5ef508e29398c34a1b2c9fc7e7507393cf2676c7` |
| uh60_high.osgb | 71655042 | `aedf4b122f92a2fccb062998f2f8d06f29ab249d73e8be088b59280b90ca8eaa` |

按文件名可初步分为固定翼、直升机、导弹、雷达和发射车，实际外观与分类待检查。目录未发现独立纹理文件；纹理可能内嵌或引用外部路径，当前不能据此判定缺失。来源和授权说明、长度单位、前向／上向轴、模型原点和动画信息待 T06 登记。

## 2. G5-T06 接入安排

Cesium 的实体模型接口以 glTF 为输入，可加载 GLB；这些 OSGB 原件需要经过格式转换再接入，不能只修改后缀。[Cesium Model 官方接口](https://cesium.com/learn/cesiumjs/ref-doc/Model.html)

- 先选一个适合当前仿真实体的样本，检查读取器和转换工具的实际兼容性，冻结工具版本、输入摘要与输出摘要；保留原始资源。
- 转换候选采用 glTF 2.0／GLB，检查几何、纹理、材质、透明度及可能的动画；记录外部资源依赖并验证本地离线加载。
- 校准长度单位、真实尺寸、前向／上向轴和原点，将资产修正变换与后端航向／俯仰／滚转分开记录；通过四向航向和姿态样本后建立实体类型到资产的显式映射。显示模型不改变后端实体类型或仿真能力。
- 核查 high／lo／low／icon 变体的实际内容，再确定远近显示策略；这些文件名不能代替三角形数、纹理占用或 LOD 验证。UH-60 原件约 71.7 MB，AH-64D 约 55.0 MB，应优先检查转换后的大小、加载和内存开销；20 实体性能随 T10 实测。
- 模型显示资格仍按 T06 的坐标、姿态和真实消息验收，资源打包与阶段发布随 T11 完成。本次不安装转换工具、不转换资源、不启动浏览器或仿真。

本登记不改变已经通过的 T01／T02 输入和资格，也不增加新的仿真场景或任务要求。
