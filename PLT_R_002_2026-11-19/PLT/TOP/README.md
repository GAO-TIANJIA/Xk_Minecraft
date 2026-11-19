> **最高优先级工作范围** 仅在当前工作区 `C:\Users\GAOTIANJIA\D\MC_CODEC` 内读取/修改；R_002 TOP 实现在本版本目录。
>
> **排序声明** 按量化顺序、亮度全局搜索、树聚类接口、输出校验和运行方式排列；迭代新到旧。
>
> **Iteration 07 | 2026-11-19 21:43:15 +08:00 | 全局启动与项目接口** 核对全局 Python 和 GPU 验收记录，补齐 R_002 的配置、输出和 Java 26.3 数据包桥接说明。
>
> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | 量化优先的编码流程** TOP 先找羊毛色板下最优倍率并量化像素，再将标签图交给 DIV 聚类。

# TOP：R_002 编码主链路

## 主流程

1. READ_SOURCE 读入 BMP/PNG RGB8。
2. Quantizer 用固定 palette 搜索全局亮度倍率，输出原 RGB 图、最近羊毛 palette 索引图、未缩放原图到所选羊毛的 SSE 和实际后端。
3. DIV 从 palette 索引图的 1×1 单元开始建二叉/四叉树，再由下向上合并相同 wool 标签。
4. D 复算量化图的 SSE；R 生成绘图计划；RDO 在计划间按 D+λR 选择；TOP 生成并校验命令文件。

## 亮度参数

- `brightness_scale` 默认为 `"auto"`，穷举 `brightness_search` 指定的等距倍率网格；默认 `[0,4]`、1025 个含端点倍率（1/256 步距）。倍率缩放值只决定羊毛标签；误差用未缩放原 RGB 与所选羊毛 RGB 计算，平局优先接近 1，再取较小倍率。
- 网格上穷举得到全局最优；这指配置网格范围内的最优，不是连续实数倍率的解析解。可将倍率改成 `[0,4]` 数值以固定不搜索。
- 摘要记录倍率、网格、CuPy/NumPy 后端和量化 SSE；调色板颜色和顺序保持原样，颜色数量不限于 2 的幂。

## GPU 后端

当前机器在 VS Code 集成终端使用全局 `C:\Python314\python.exe`（Python 3.14.7）。已验收的共享依赖为 NumPy 2.5.5、CuPy 14.2.0、NVIDIA CUDA Runtime 与 NVRTC 13.5.37，以及 CUDA Pathfinder 1.9.1，均位于 `C:\Python314\Lib\site-packages`。普通权限即可编码；全局依赖维护由管理员执行。 GPU 量化与 CPU 树压缩的范围、依赖维护和启动命令以 [R_002 启动说明](../../README.md) 为准。

## 运行和输出

从 R_002 目录执行：

```powershell
python -m PLT.TOP.plt_top .\config.example.json
```

摘要格式为 `PLT-TOP-summary-v3`。PLT JSON 仍为 version 1，新增的倍率/后端信息只进入 score 元数据，已有图像、palette、partition、操作和命令字段语义保持不变。写文件前校验分区覆盖、计划重放、量化 D、坐标及 FILL/命令限制。

## 桥接边界

输出 `SETB` / `FILL` 文本兼容工作区内的 Minecraft Java 26.3 bridge。TOP 只生成文件，不执行命令或修改世界。输入格式及 PNG alpha 处理见 [READ_SOURCE](../READ_SOURCE/README.md)。

## 迭代记录（新到旧）

- **Iteration 07 | 2026-11-19 21:43:15 +08:00 | 全局启动与项目接口** 核对全局 Python 和 GPU 验收记录，补齐 R_002 的配置、输出和 Java 26.3 数据包桥接说明。

- **Iteration 02 | 2026-11-19 18:47:33 +08:00**：替换 RDO 输入为单个已量化聚类候选；加入智能倍率、GPU 后端和量化 SSE 一致性校验。
- **Iteration 01 | 2026-11-19 18:38:13 +08:00**：曾使用固定亮度倍率和候选深度搜索，已由 Iteration 02 替换。
