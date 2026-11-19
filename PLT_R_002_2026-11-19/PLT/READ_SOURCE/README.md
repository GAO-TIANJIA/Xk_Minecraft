> **最高优先级工作范围** 阅读与修改范围仅限当前工作区 C:/Users/GAOTIANJIA/D/MC_CODEC。不得读取或搜索工作区外的路径；缺失的外部信息标为待定。
>
> **本文排序声明** 先列统一入口，再列 BMP/PNG 支持范围和明确不支持项。
>
> **R_002 Iteration 01 | 2026-11-19 18:38:13 +08:00 | 沿用输入模块** READ_SOURCE 从 R_001 原样复制；BMP/PNG 统一 RGB8 入口不变，亮度缩放在 TOP 的 SSE 输入预处理阶段进行。
>
> **Iteration 07 | 2026-11-19 17:44:27 +08:00 | R_001 alpha 输入修复** R_001 支持 alpha/tRNS PNG，并在输出 RGB8 前合成到白色背景。

# READ_SOURCE：BMP/PNG 图像输入

公共入口 PLT.READ_SOURCE.read_image(path, ImageReadConfig(max_pixels=...)) 根据内容签名读取 BMP 或 PNG，并返回 PLT.model.RGBImage。两种输入统一成顶行优先、紧密排列的 RGB8 bytes，供后续 DIV/D/RDO 共用。

TOP 的 image 配置路径现在可以指向 BMP 或 PNG；文件扩展名不决定解码器。原有 read_bmp、BMPReadConfig、write_bmp 保留，后者继续供 PLT JSON 解码输出重建 BMP。

## BMP 支持

- Windows DIB header 至少 40 字节。
- 24-bit BI_RGB 未压缩。
- 支持正/负高度、行填充、像素偏移；拒绝 32-bit、alpha、调色板和压缩 BMP。
- 默认最多 16,777,216 像素；由 ImageReadConfig.max_pixels 配置。

## PNG 支持

- 非交错 grayscale 1/2/4/8/16-bit、RGB 8/16-bit、indexed color 1/2/4/8-bit、grayscale-alpha 8/16-bit、RGBA 8/16-bit。
- 解码五种 scanline filter，检查 chunk CRC 和结构，输出 RGB8。
- alpha 与 tRNS 透明度在输出 RGB8 前合成到白色背景；背景当前固定。
- Adam7 interlace、未知 critical chunk、损坏数据仍明确报错。
- PNG 文件上限为 512 MiB；max_pixels 检查 PNG 头声明的宽高，限制解压分配。

## 错误和颜色边界

统一分派错误为 ImageReadError；具体 BMP/PNG reader 也可单独调用并产生格式专属错误。透明像素先合成到白色，再以 RGB8 进入 SSE；背景暂不支持配置覆盖。当前不应用 ICC、gamma 或 EXIF 色彩配置。

具体集成/遗漏任务和支持边界见 [TASKS.md](TASKS.md)。

