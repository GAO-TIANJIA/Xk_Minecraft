> **最高优先级工作范围** 阅读与修改范围仅限当前工作区 C:/Users/GAOTIANJIA/D/MC_CODEC。不得读取或搜索工作区外的路径；缺失的外部信息标为待定。
>
> **本文排序声明** 先列统一读入接口和格式边界，再列已完成合并方式、遗漏项与迭代记录；迭代记录新到旧。
>
> **R_002 Iteration 01 | 2026-11-19 18:38:13 +08:00 | 沿用输入契约** 读取器从 R_001 原样复制；图像只在 TOP 的匹配预处理阶段统一缩放亮度，READ_SOURCE 不变更 RGB 解码值。
>
> **Iteration 07 | 2026-11-19 17:44:27 +08:00 | R_001 alpha PNG 支持** 支持 PNG alpha/tRNS 并白底合成；仅更新 R_001 副本。

# READ_SOURCE：统一图像读入

## 已完成的统一接口

包级入口 PLT.READ_SOURCE.read_image(path, ImageReadConfig(max_pixels=...)) 按文件签名分派 BMP 或 PNG，并统一返回 PLT.model.RGBImage。图像为左上角起点、逐行紧密 RGB8 bytes。

TOP 的编码入口改用 read_image；配置字段仍为 image，原有 BMP 配置和 read_bmp 保持兼容。解码 JSON 时 write_bmp 仍用于输出重建 BMP。

## PNG 首版支持边界

- PNG 签名检查、chunk 边界和 CRC 校验。
- 支持非交错 grayscale（1/2/4/8/16-bit）、RGB（8/16-bit）、indexed color（1/2/4/8-bit）、grayscale-alpha（8/16-bit）及 RGBA（8/16-bit）；统一转换到 RGB8。
- 支持 PNG scanline 的 None、Sub、Up、Average、Paeth 五种过滤器。
- alpha 与 tRNS 透明度在输出 RGB8 前合成到白色背景；背景当前固定。
- 拒绝 Adam7 interlace、缺失/越界调色板索引、未知 critical chunk 和损坏 zlib 数据。
- 单文件上限 512 MiB；max_pixels 在 IHDR 后校验。

## 与 BMP 的合并方式

1. PNG 解码实现在 READ_SOURCE/png.py；统一分派实现在 READ_SOURCE/image_reader.py；公共导出集中于 READ_SOURCE/__init__.py。
2. BMP 解析继续由 bmp.py/bmp_reader.py 负责；BMPReadConfig 作为 ImageReadConfig 的兼容别名。低层 read_bmp、公开 read_bmp、read_png 均保留，但 TOP 统一使用 read_image。
3. BMPReadError 与 PNGReadError 由 read_image 转成统一 ImageReadError。错误应包含输入路径和格式原因。
4. 后续格式只在 READ_SOURCE 增加解码器，并返回相同 RGBImage；TOP、DIV、D 不得按扩展名自行分支。

## 输入到输出检查发现的未实现项

- PNG Adam7 interlace 当前明确不支持；不把 PNG 支持描述为无条件全格式。
- 读取器目前不处理 EXIF/ICC/gamma 色彩配置；PNG 样本值按文件解码出的 RGB 样本使用，不保证与浏览器/游戏截图的色彩管理结果相同。
- TOP 配置示例已将 image 指向 PNG；TOP 按签名统一支持 BMP/PNG，扩展名不作为格式判定条件。
- 配置像素上限对 PNG 解压后的维度生效；PNG 文件字节本身另受 512 MiB 上限限制。
- 统一 `ImageReadError` 保留文件路径和底层格式原因，便于 TOP CLI 输出可定位错误。

## 完成条件

BMP 和支持范围内 PNG 均通过包级 read_image 返回相同类型；TOP 不根据扩展名分派；BMP 旧入口与 JSON 解码写 BMP 路径保持兼容；不支持的格式明确报错。

