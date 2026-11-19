> **最高优先级工作范围** 阅读与修改范围仅限当前工作区 C:/Users/GAOTIANJIA/D/MC_CODEC。不要读取工作区之外的路径，也不要搜索父目录、用户目录或其他磁盘；缺失的外部信息标为待定。
>
> **本文排序声明** 先列活动 D 接口与类型边界，再列失真语义及辅助 API。
>
> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | 沿用 D/SSE** D 代码和数值定义从 R_001 原样复制；brightness_scale 仅决定羊毛标签，D 仍以未缩放原 RGB 为误差参考。
>
> **Iteration 04 | 2026-11-19 | 接口收敛实施** 已修正主接口注解并建立 `PLT.D` 公共门面，TOP/RDO 已切换导入；未运行测试。

# D：RGB SSE

## TOP v1 活动接口

- IntegralImage(image: PLT.model.RGBImage)，别名 RgbIntegral：建立 64-bit RGB 和/平方和积分表。
- sse_candidate(candidate, palette_map, integral) 返回非负整数 RGB SSE。
- reconstruct_candidate(candidate, width, height, palette_map) 返回紧密 RGB bytes，并检查覆盖完整、无重叠和范围。

palette_map 是 block_id 到 PLT.model.PaletteEntry 的映射。TOP 使用这条路径评分并在输出前复核所选 D。

活动函数的主模型注解使用 `PLT.model` 数据类型。`PLT.D` 包级门面导出活动接口，TOP/RDO 从该门面导入。

## 失真定义

D 为源图与调色板重建图的逐像素 RGB8 通道平方误差和。首版不归一化，不做 gamma 校正或感知色差。BMP 输入不接受 alpha/32-bit，因此 D 中无 alpha 项。

## 并行辅助接口边界

D/sse.py 还保留 sse_from_segments、reconstruct 等兼容辅助函数，使用 PLT.models 中的 Segment/Rect 数据结构；它们不从 `PLT.D` 包级门面导出。PLT.models.RgbImage 是 PLT.model.RGBImage 的别名。此几何不应与 PLT.DIV.model.Rect 或 PLT.RDO.rdo.Rect 混用。TOP 活动接口继续使用 PLT.model。

RDO.rdo.py 的 DModule Protocol 是另一套可插拔接口，目前 TOP 未调用。若接入，需明确 RGBImage/Raster 转换和相同 SSE 结果契约。

## 性能与边界

积分表 CPU 路径已实现；另有直接栅格 SSE/重建路径。CUDA 和其他色差定义尚未实现。D 不承担颜色采样、候选搜索、命令计划、世界坐标或文件输出。

下一轮 D 的公共入口与类型提示修改指令见 [TASKS.md](TASKS.md)。

