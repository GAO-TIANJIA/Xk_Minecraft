# R_002 使用说明

> 本文面向 R_002（Minecraft Java 26.3 羊毛绘图编解码器）的编码器和配套桥接器，覆盖安装、配置、输出、进游戏、验证与排错。
> 示例数字来自 2026-11-19 本机实测（Python 3.14.7、NumPy 2.5.5、CuPy 14.2.0、RTX 5070 Ti）；换机器会变。
> 代码成型思路与时间线见 [DESIGN_TIMELINE.md](DESIGN_TIMELINE.md)。

## 0. 一句话流程

```text
BMP/PNG → 量化到 16 色羊毛 → 树聚类 → RDO 选绘图计划 → commands.txt
commands.txt → plot_batch.py → 存档数据包 → /reload → /function plot_interface:run
```

编码器只生成文件，不连接游戏、不修改世界；桥接器只写存档里的数据包，不联网、不使用 RCON。

## 1. 能力与边界

- 输入：无压缩 24-bit BMP；PNG 支持非交错灰度、RGB、索引色、灰度 alpha、RGBA（1/2/4/8/16-bit，统一转 RGB8）。PNG 文件上限 512 MiB；宽高超过 `max_pixels` 会在解码前被拒绝。
- 输出：有序 `SETB` / `FILL` 文本、`summary.json`、可选 `image.plt.json`。
- 颜色：默认 16 种 Minecraft Java 26.3 羊毛；色值来自官方客户端纹理的算术平均 RGB（`wool_palette.json` 记录来源与哈希）。
- 世界：只做坐标映射；实际放置由桥接器 + 游戏完成。
- 不支持：Adam7 交错 PNG、ICC/gamma/EXIF 色彩管理、RCON、基岩版、Java 1.10+ 的跨版本兼容声明（当前只面向 26.3）。
- 成本参数 `lambda`、`C_fill`、`C_setb` 是配置值，不是实测服务器性能。

## 2. 两种目录形态

仓库内和发布包内的 `PLT/` 子树相同，差别只在桥接器和示例位置。

| 位置 | 编码器根目录 | 桥接器 | 示例图 |
|---|---|---|---|
| 仓库 | `PLT\R_002` | `PLOT_INTERFACE\plot_batch.py` | `PLT\REFERENCE_FIG\002.png` |
| 发布包 | 解压后的包目录 | `bridge\plot_batch.py` | `examples\002.png` |

R_002 目录结构（发布包同构）：

| 路径 | 作用 |
|---|---|
| `PLT\` | 编码器代码（READ_SOURCE / D / DIV / R / RDO / TOP） |
| `config.example.json` | 端到端示例配置 |
| `wool_palette.json` | 16 色羊毛颜色与来源元数据 |
| `requirements.txt` | CPU 基础依赖 |
| `requirements-gpu-cupy13x.txt` | 可选 GPU 依赖 |
| `commands.txt`、`summary.json`、`image.plt.json` | 默认输出（运行后生成） |
| `USAGE.md`、`DESIGN_TIMELINE.md` | 本文与设计时间线 |

发布包额外包含：

| 路径 | 作用 |
|---|---|
| `bridge\plot_batch.py` | 桥接器副本（与仓库 `PLOT_INTERFACE\plot_batch.py` 相同） |
| `bridge\commands.example.txt` | 桥接器最小示例 |
| `examples\002.png` | 示例输入图（168×177） |
| `examples\expected\` | 示例输出（commands / summary / image.plt.json） |
| `MANIFEST.sha256` | 发布包文件校验和 |

## 3. 环境要求

- Python：本机验收 **3.14.7**；编码器只用标准库 + NumPy。换机器请用能安装 `requirements.txt` 中 NumPy 版本的 3.11+ 解释器。
- 依赖（CPU）：

  ```powershell
  python -m pip install -r requirements.txt
  ```

  当前声明 `numpy>=2.5,<3`。

- 可选 GPU（CuPy）：

  ```powershell
  python -m pip install -r requirements-gpu-cupy13x.txt
  ```

  声明 `cupy-cuda13x>=14.2,<15`、`nvidia-cuda-runtime>=13.2,<14`、`nvidia-cuda-nvrtc>=13.2,<14`。
  有可用 GPU 时会走 CuPy；**GPU 可见但运行失败会直接报错，不会静默退回 CPU**；只有检测不到设备时才用 NumPy。

- 自检：

  ```powershell
  python -c "import sys, numpy; print(sys.executable); print(numpy.__version__)"
  python -c "import cupy; print(cupy.__version__, cupy.cuda.runtime.getDeviceCount())"
  ```

- 本机验收用的是全局 `C:\Python314\python.exe`，没有依赖项目内 `.venv`；换机器时用哪个解释器都行，只要依赖可见。

## 4. 快速开始

在仓库里：

```powershell
Set-Location -LiteralPath .\PLT\R_002
python -m PLT.TOP.plt_top .\config.example.json
```

在发布包里：

```powershell
Set-Location -LiteralPath "解压目录\PLT_R_002_2026-11-19"
python -m PLT.TOP.plt_top .\config.example.json
```

示例输出（本机实测，CPU/GPU 结果应一致，只有 `backend` 不同）：

```text
Wool quantization: brightness_scale=1.000000, backend=cupy, evaluated_scales=1025
PLOT_INTERFACE bridge options: --max-blocks 32768 --max-commands 65536 (0 means unlimited)
Wrote 10521 commands (FILL=385, SETB=10136); D=22139519, R=2412.2, J=2.21781e+07
```

退出码：`0` 成功；`2` 配置/输入/规划错误（错误信息以 `error:` 写到 stderr）。

生成文件：

| 文件 | 内容 |
|---|---|
| `commands.txt` | 10,521 行 `SETB` / `FILL` |
| `summary.json` | 参数、树/量化信息、D/R/J、分区与命令列表 |
| `image.plt.json` | 自包含 PLT v1 流，可解码回 BMP/命令 |

示例配置的输出路径是 `out\commands.txt` 等（发布包）；仓库示例写在 `PLT\R_002` 根目录。输出目录会自动创建。

## 5. 配置详解

配置是严格 JSON（UTF-8，允许 BOM）：未知字段、重复键、类型错误、非法数值都会报错，不会静默忽略。

### 5.1 字段总表

| 字段 | 必填 | 说明 |
|---|---|---|
| `image` | 是 | 输入 BMP/PNG 路径 |
| `output` | 是 | 指令文本输出路径 |
| `summary` | 否 | 摘要输出路径；省略/null 不写 |
| `plt` | 否 | PLT JSON 输出路径；省略/null 不写 |
| `palette` | 是 | 非空数组，每项 `{block_id, rgb}`；`block_id` 唯一，`rgb` 为 3 个 0–255 整数 |
| `lambda` | 是 | 有限非负数，`J = D + lambda * R` |
| `costs` | 是 | 恰好含 `fill`、`setb`，均为有限非负数 |
| `mapping` | 是 | `origin`、`x_step`、`y_step` |
| `limits` | 是 | `max_pixels`、`max_fill_blocks`、`max_commands`、`max_world_coord` |
| `brightness_scale` | 否 | `"auto"`（默认）或 0–4 的数值 |
| `brightness_search` | 否 | `min_scale`、`max_scale`、`steps`（默认 0、4、1025） |
| `initial_background_block` | 否 | null 或 palette 中的 `block_id` |
| `search` | 否 | 兼容 R_001 旧配置，R_002 忽略 |

所有路径：相对路径以**配置文件所在目录**为基准，支持 `~`；`config`、`image`、`output`、`summary`、`plt` 的解析结果必须互不相同。

### 5.2 palette

```json
{ "block_id": "minecraft:white_wool", "rgb": [234, 236, 237] }
```

- `block_id` 可省略 `minecraft:` 前缀，会被规范化；必须是桥接器 regex 接受的名字/状态。
- 颜色数量不限 2 的幂，也不会自动补色；**列表顺序决定量化平局**。
- 默认 16 色羊毛的 RGB 是 26.3 客户端 `assets/minecraft/textures/block/<color>_wool.png` 全部不透明像素的 sRGB 算术平均，四舍五入；来源记录在 `wool_palette.json`。
- 想换方块（例如混凝土）时，必须同时确认目标版本的方块名与桥接器语法，并自行提供可信 RGB。

### 5.3 亮度搜索

```json
"brightness_scale": "auto",
"brightness_search": { "min_scale": 0.0, "max_scale": 4.0, "steps": 1025 }
```

- `auto`：在 `[min_scale, max_scale]` 上取 `steps` 个含端点等距倍率（默认 1/256 步距），逐个量化并计算误差，取全局最小。
- 倍率只决定每个像素选哪个羊毛标签；**误差始终用未缩放原图 RGB** 与所选羊毛 RGB 计算，避免"整体压暗"取巧。
- 平局优先接近 1.0 的倍率，再取较小倍率。
- 固定倍率：把 `brightness_scale` 写成 0–4 的数（此时不搜索，`searched_scales=1`）。
- `steps` 范围 2–4097；`min_scale < max_scale`。

### 5.4 成本与 lambda

```json
"lambda": 16.0,
"costs": { "fill": 1.0, "setb": 0.2 }
```

- `R = N_fill * C_fill + N_setb * C_setb`，`J = D + lambda * R`。
- `D` 是原图到所选羊毛颜色的 RGB 通道平方误差和；量化后 `D` 固定，RDO 主要在比较 `R`。
- 两个成本必须同量纲；当前默认值只是示例，不是服务器标定值。
- 想减少命令数：提高 `lambda` 或 `C_setb`；想更贴近原图：降低 `lambda`。

### 5.5 坐标映射

```json
"mapping": {
  "origin": [0, 64, 0],
  "x_step": [1, 0, 0],
  "y_step": [0, 0, 1]
}
```

- 图像像素 `(x, y)` 的世界坐标 = `origin + x * x_step + y * y_step`（`(0,0)` 就是 `origin`）。
- `x_step`、`y_step` 必须是**互相垂直的有符号单位轴**（只有一个分量非 0，取 ±1）。
- 默认是 XZ 水平面：图像 x 向 +X，图像 y 向 +Z，y 固定在 64。
- 竖直墙：`x_step=[1,0,0]`、`y_step=[0,1,0]`，`origin` 取墙左下角。
- 翻转：把对应轴的符号取反（例如 `x_step=[-1,0,0]`）。
- 映射后坐标必须落在 `limits.max_world_coord`（≤30,000,000）内。

### 5.6 限制

| 字段 | 含义 | 0 的含义 |
|---|---|---|
| `max_pixels` | 输入图像最大像素数 | 不允许 0 |
| `max_fill_blocks` | 单条 `FILL` 最大方块数 | 0 = 不限（但游戏侧仍有限制） |
| `max_commands` | 计划最大命令数 | 0 = 不限 |
| `max_world_coord` | 世界坐标绝对值上限 | 必须在 1–30,000,000 |

默认 `32768` / `65536` 与桥接器默认值一致；如果改了，桥接时传相同的 `--max-blocks` / `--max-commands`（`summary.json` 的 `bridge.recommended_options` 会给出建议）。

### 5.7 initial_background_block

可选。设置后 RDO 会额外评估"先铺满整张画布、再覆盖不同色块"的计划（`overlay_*`），所有铺底与覆盖都计入 `R`。适合大面积同色的图；不需要就保持 `null`。

### 5.8 常见改法

| 目标 | 改哪里 |
|---|---|
| 换图 | `image` |
| 换位置/高度 | `mapping.origin` |
| 做竖墙 | `x_step=[1,0,0]`、`y_step=[0,1,0]` |
| 画面镜像 | 把 `x_step` 或 `y_step` 取反 |
| 命令更少 | 提高 `lambda` / `costs.setb` |
| 更大图 | 提高 `max_pixels`；同时看显存/内存 |
| 固定亮度 | `brightness_scale` 写数值 |

## 6. 输出文件

### 6.1 commands.txt

每行一条，UTF-8，无注释：

```text
SETB 0 64 0 minecraft:white_wool
FILL 1 64 1, 8 64 8 minecraft:white_wool
```

- 坐标是绝对整数；`FILL` 两个端点都包含在区域内。
- `FILL` 的宽高是 2 的幂（由树分割保证），面积不超过 `max_fill_blocks`。
- 方块名使用 26.3 风格（名称 + 可选方块状态），不是旧版数字 ID。
- 顺序即执行顺序；先写的会被后写的覆盖。

### 6.2 summary.json

格式标识 `PLT-TOP-summary-v3`。顶层：

| 字段 | 内容 |
|---|---|
| `config`、`input` | 本次运行的绝对路径 |
| `image` | 宽、高、像素格式 |
| `parameters` | 亮度倍率/规则/搜索、后端、量化 SSE、树聚类说明、树画布、lambda、成本、映射、限制、调色板 |
| `bridge` | 桥接器 profile 与建议参数 |
| `result` | `D`、`R`、`J`、`N_fill`、`N_setb`、`N_total`、`plan`、候选/计划计数、`partition`、`commands` |

示例（本机）：`D=22139519`、`R=2412.2`、`J=22178114.2`、`N_fill=385`、`N_setb=10136`、`N_total=10521`、`plan=hybrid`、`partition` 7,476 个矩形、树画布 256×256。

### 6.3 image.plt.json

`format="plt-block-codec"`、`version=1`，自包含：

- `image`、`palette`、`partition`、`draw_plan`（有序 `operations`）、`world_mapping`、`limits`、`score`（D/R/J、倍率、后端等）。
- 它**不是**指令文件；给解码器、校验和二次分析用。
- 解码可重建 BMP 与命令：

  ```powershell
  python -m PLT.TOP.plt_codec decode .\image.plt.json `
    --max-pixels 1048576 `
    --output-bmp .\reconstruction.bmp `
    --commands .\decoded_commands.txt
  ```

- 需要 `plt` 配置路径才能用 `encode` 重写：

  ```powershell
  python -m PLT.TOP.plt_codec encode .\config.example.json
  ```

### 6.4 写入方式

三个文件都先写同目录临时文件、`fsync` 后 `os.replace` 原子替换；不会留下半截文件。输出目录不存在会自动创建。

## 7. 在 Minecraft 里使用（Java 26.3 数据包桥接）

### 7.1 前置

- Minecraft Java **26.3** 单人存档目录（含 `level.dat` 的那一层）。
- 该世界允许命令（作弊开启）。
- 建议先备份整个存档目录。

### 7.2 预检（不写存档）

仓库内：

```powershell
python .\PLOT_INTERFACE\plot_batch.py .\PLT\R_002\commands.txt --world-dir "<存档目录>" --dry-run
```

发布包内：

```powershell
python .\bridge\plot_batch.py .\examples\expected\commands.txt --world-dir "<存档目录>" --dry-run
```

`--dry-run` 会校验并逐行打印编译后的命令；大文件输出很长，可只取前几行预览：

```powershell
python .\bridge\plot_batch.py .\examples\expected\commands.txt --world-dir "<存档目录>" --dry-run | Select-Object -First 3
```

### 7.3 安装数据包

去掉 `--dry-run` 再执行一次。脚本会：

1. 校验整个指令文件（坐标、方块名、`FILL` 体积、命令数）；
2. 在 `<存档>\datapacks\plot_interface\` 写入 `pack.mcmeta` 与 `data\plot_interface\function\run.mcfunction`；
3. 写入 `.plot_interface_generated` 标记。

如果同名目录存在但没有该标记，脚本会拒绝覆盖。

### 7.4 游戏内执行

```text
/reload
/function plot_interface:run
```

数据包格式：`pack.mcmeta` 使用 `min_format [121,0]`、`max_format 121`，与 26.3 客户端 `version.json` 的 `data_major=121` 对应。

### 7.5 执行注意

- **区块必须已加载**：未加载区块里的 `fill`/`setblock` 会失败且不报错。站在绘图区附近（或上方）再执行；大范围可先 `/forceload add <x1> <z1> <x2> <z2>`，完成后 `/forceload remove all`。
- **一个 tick 执行完整个函数**：10,521 条命令会有明显卡顿，属正常。
- **覆盖语义**：默认 replace，会替换区域内所有方块；先备份或确认区域为空。
- **上限**：单条 `FILL` 默认 32,768 方块；函数默认 65,536 条命令。本示例最大 `FILL` 1,024、总计 10,521，均在上限内。
- **无内置撤销**：清空可 `/fill x1 y1 z1 x2 y2 z2 air`（168×177=29,736 方块，单条可完成）。
- 修改 `commands.txt` 后重新跑桥接脚本，再 `/reload` + `/function`。

### 7.6 移除

删除 `<存档>\datapacks\plot_interface` 整个目录即可；标记文件表示它由脚本生成，可安全删除。

## 8. 验证与复现

- **与示例对照**（发布包）：`examples\expected\commands.txt` 与本机重新生成的 `commands.txt` 应逐字节相同；`image.plt.json` 也应相同。`summary.json` 只有 `config`/`input` 的绝对路径会不同。
- **PLT 解码回放**：解码出的 `decoded_commands.txt` 应与 `commands.txt` 一致（同一 PLT 流）。
- **哈希校验**：

  ```powershell
  Get-FileHash -Algorithm SHA256 .\commands.txt
  Get-FileHash -Algorithm SHA256 .\image.plt.json
  ```

  发布包的 `MANIFEST.sha256` 给出全部文件校验和。

- **游戏侧抽查**：

  ```text
  /execute if block 0 64 0 minecraft:white_wool run say ok
  ```

## 9. 常见问题

| 现象 | 可能原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: No module named 'numpy'` | 解释器不对/没装依赖 | 先 `python -c "import sys; print(sys.executable)"`，再 `python -m pip install -r requirements.txt` |
| `ModuleNotFoundError: No module named 'PLT'` | 不在含 `PLT\` 的目录运行 | `cd` 到 R_002（或发布包）根目录 |
| 显示 `backend=numpy` 但机器有 GPU | CuPy 未装/驱动不可见 | 装 `requirements-gpu-cupy13x.txt`，用 `cupy.cuda.runtime.getDeviceCount()` 自检 |
| GPU 可见但运行报 CUDA/CuPy 错误 | 设计上不静默回退 | 修驱动/依赖；或临时移除 CuPy 走 CPU |
| `interlaced PNG is unsupported` | Adam7 交错 | 用图像工具另存为非交错 |
| `image ... exceeds ... max_pixels` | 图太大 | 提高 `limits.max_pixels`（注意内存/显存） |
| `FILL covers ... above configured limit` | `max_fill_blocks` 太小 | 提高该值，并给桥接器同样的 `--max-blocks` |
| `plan has ... commands, above configured limit` | `max_commands` 太小 | 提高该值，或提高 `lambda`/`costs.setb` 减少命令 |
| `mapped ... exceeds configured limit` | 画面超出坐标范围 | 调整 `mapping.origin` |
| 桥接报 `line N: ...` | 指令行不合法/被手改 | 用编码器重新生成，或按提示修该行 |
| 游戏里没反应/只画了一部分 | 没 `/reload`、区块未加载、无权限 | `/reload`、站到附近、`/forceload`、确认作弊开启 |
| 数据包被标为不兼容 | 不是 26.3 | 使用对应版本的桥接器与方块语法 |

## 10. 示例数据与性能

示例图 `002.png`（168×177）在本机的一次完整运行：

| 指标 | 值 |
|---|---|
| 后端 | CuPy（RTX 5070 Ti） |
| 亮度搜索 | 1025 个倍率，选中 1.0 |
| 树画布 | 256×256（补边不输出） |
| 分区矩形 | 7,476 |
| 计划 | hybrid |
| 命令 | 10,521（FILL 385 + SETB 10,136） |
| 影响方块 | 29,736 |
| D / R / J | 22,139,519 / 2,412.2 / 22,178,114.2 |
| 耗时 | 约 3.8 秒（本机） |

历史 CPU 基线（R_001，不同算法）对 140×178 图曾记录约 46.8 秒、峰值工作集约 2.5 GiB，只作为"CPU 路径会很慢"的参考，不能与 R_002 的 GPU 数字直接比较。

## 11. 设计边界

- 成本、`lambda`、桥接限制均未在本项目里针对服务器标定。
- 目标版本固定 26.3；换版本需重新核对 `pack.mcmeta` 格式和方块语法。
- PNG 透明度统一合成到白底，暂不可配置背景；不应用 ICC/gamma/EXIF。
- 没有自动化测试套件；每次运行靠内置的分区/计划/D/命令数一致性校验兜底。
- `PLT/DIV/segmentation.py`、`PLT/RDO/rdo.py` 是历史 alternate 实现，不在 R_002 主链路。

## 12. 延伸阅读

- [DESIGN_TIMELINE.md](DESIGN_TIMELINE.md)：代码成型思路、模块地图、逐小时时间线。
- `PLT/TOP/README.md`：TOP 主链路接口。
- `PLT/READ_SOURCE/README.md`：BMP/PNG 支持边界。
- 仓库 `PLOT_INTERFACE/README.md`：桥接器完整说明（发布包内为 `bridge/plot_batch.py`）。
