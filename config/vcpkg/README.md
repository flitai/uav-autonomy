# 固定 Windows 依赖配方

版本、源码 URL／SHA-512／SHA-256、81 个 Boost 历史 tree 和辅助工具见 [来源清单](../windows-dependencies.json)。操作与验收见 [T02 报告](../../docs/g2-dependencies-validation.md)。

`ports/` 优先于 registry；只改 baseline 无法锁定这些 overlay，因此构建记录同时计算本目录所有文件的 SHA-256。六项非 Boost 库版本沿用 `OpenUxAS/infrastructure/specs/`，源码包由 vcpkg 校验 SHA-512；构建前后还核对已缓存的固定源码。

- cppzmq 参考历史 tree `c95be3f1cd3205c897f4f9ed4af464624de3ce4d`，保留 4.2.2 的两个头文件，替换废弃辅助调用并导出静态 libzmq 传递目标。
- pugixml 参考 `0af6c22cb58a218893ca193a5f5d29d7d1753355`，增加原 Anod `as_int64` 补丁，固定窄字符。SQLiteCpp 仅修复外部库发现、安装布局和 MSVC CRT 选项。
- Boost 辅助 ports 复制清单登记的历史 tree：build 为 1.74.0#0→#1，modular-build-helper 为 1.74.0#2→#3；vcpkg-helpers 保持 7#1。其余历史模块通过 overrides 锁定，未复制成整包配方。
- Boost.Build 只增加 v143 识别、UTF-8 进程 manifest 和 MSVC 响应文件 BOM；辅助配方固定 cl 路径、vc143 库名、单独的 include 参数与并发数。没有将 v143 伪装为旧工具集。
- `cmake/spdx-cmake331.cmake` 改编自固定 vcpkg 的 `scripts/cmake/z_vcpkg_spdx.cmake`，只替换 CMake 4.x JSON 字符串编码调用；SPDX 字段与校验值保持。

复制／改编的 vcpkg 配方适用 [MIT 许可证](LICENSE-vcpkg.txt)。各第三方源码的原始许可证随安装包 `share/<port>/copyright` 保留；本目录不重新许可第三方源码。

下载和工具在 `.tools/`，构建／候选／故障／正式批次在 `out/`。不对系统执行全局 vcpkg 集成。主机工具使用固定 vcpkg 元数据的 PowerShell 7.6.3、7-Zip／7zr 26.02、pkgconf 2.5.1-1 和 MSYS2 runtime 3.6.5-1；它们仅作为构建工具，业务库均由 MSVC 原生编译。
