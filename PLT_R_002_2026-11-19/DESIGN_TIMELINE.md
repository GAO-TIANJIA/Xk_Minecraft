# R_002 代码成型思路与时间线

> 目的：解释"当前代码为什么长成这样"，并把模块、文件时间、文档迭代和真实产物对应起来。
> 证据来源：`PLT/README.md`、`PLT/PLT.md`、`R_001/README.md`、`R_002/README.md`、`PLT/TOP/*/README.md` 的迭代记录，以及本工作区文件的修改时间（均为 2026-11-19，UTC+8）。
> 使用说明见 [USAGE.md](USAGE.md)。

## 1. 目标与约束

R_002 要解决的问题很具体：把一张 BMP/PNG 变成 Minecraft Java 26.3 能执行的方块指令，并且：

- **本地生成**：编码器不连接游戏、不需要服务器、不需要 RCON。
- **可复现**：同一输入 + 同一配置必须得到同一输出；不依赖随机数或时钟。
- **可审计**：调色板、坐标映射、成本、限制全部显式配置；输出带摘要和可解码的 PLT JSON。
- **可分离**：编码（离线）与放置（游戏内）拆成两个工具，互不依赖。
- **可迭代**：R_001/R_002 各自是自包含发布目录，避免跨版本 import 漂移。

## 2. 端到端数据流

```text
BMP/PNG
  └─ READ_SOURCE.read_image ──> RGBImage (RGB8)
        └─ TOP.quantizer.quantize_to_palette
              ├─ 亮度网格搜索（1025 个倍率，可固定）
              ├─ 最近羊毛颜色逐像素量化 ──> indices + 量化 SSE
              └─ CuPy（有 GPU）或 NumPy
                    └─ DIV.cluster_quantized_pixels
                          └─ 二叉/四叉树自底向上合并同色 ──> 1 个分区（7,476 矩形）
                                └─ D（积分图 SSE） + R（绘图计划成本）
                                      └─ RDO.select_candidate：J = D + λR
                                            ├─ all_fill / all_setb / hybrid
                                            └─ 可选 overlay_*（initial_background_block）
                                                  └─ TOP 校验（覆盖/重放/D/命令数/坐标）
                                                        ├─ commands.txt（SETB/FILL）
                                                        ├─ summary.json（参数与结果）
                                                        └─ image.plt.json（可解码 PLT v1）

commands.txt ──> PLOT_INTERFACE/plot_batch.py ──> 存档 datapacks/plot_interface
                                                      └─ /reload → /function plot_interface:run
```

## 3. 关键设计取舍

### 3.1 先量化，再聚类（R_002 的核心转向）

- **问题**：CPU 基线（R_001 及 `PLT/TOP`）让 DIV 直接在原图上生成分割候选，RDO 在多个候选间比较。树/矩形合并会改变像素颜色，导致"失真 D"和"命令成本 R"耦合，搜索空间大且难以保证分区精确。
- **选择**：R_002 先把每个像素固定到 16 色羊毛中的一个标签，再做"只合并相同标签"的树聚类。这样分区精确复原量化图，`D` 固定，RDO 只需比较命令成本。
- **代价**：颜色精度被 16 色限制；用亮度网格搜索补偿整体明暗；不再支持"合并不同颜色换取更少命令"。
- **副作用（好的）**：调色板数量不必是 2 的幂，不需要补色/重排，颜色顺序只用于平局决胜。

### 3.2 亮度网格搜索

- **问题**：没有目标方块/光照的标定数据，固定倍率在偏暗或偏亮的图上会整体选错羊毛。
- **选择**：`brightness_scale="auto"` 时在 `[0,4]` 上取 1025 个含端点等距倍率；缩放后的 RGB **只用来选标签**，误差始终用未缩放原图与所选羊毛 RGB 计算；平局优先接近 1.0，再取较小倍率。
- **边界**：这是"配置网格上的穷举最优"，不是连续实数上的解析最优；固定倍率可跳过搜索。

### 3.3 二叉/四叉树聚类

- **画布**：宽、高分别补到最近的 2 的幂（示例 168×177 → 256×256），补出的哨兵像素 `-1` 不参与输出。
- **合并**：从 1×1 单元向上；两个轴都大于 1 时四叉，只剩一个轴时二叉；只有所有有效子节点标签相同才合并。
- **输出**：取"极大同色节点"，得到边长为 2 的幂、互不重叠、完整覆盖原图的矩形分区；顺序按 `(y, x, height, width, block_id)`，保证确定性。
- **为什么**：矩形与 2 的幂天然适合 `FILL`；树深由补齐后的尺寸决定，不需要 `max_splits` 之类的人工深度参数。

### 3.4 RDO 计划族

- **候选**：树聚类只产生 1 个分区候选（示例 `candidate_count=1`）。
- **计划**：`all_fill`、`all_setb`、`hybrid` 三种；`hybrid` 对每个矩形比较"整块 FILL"和"逐像素 SETB"的成本，取便宜者。
- **铺底**：配置 `initial_background_block` 时追加 `overlay_all_fill` / `overlay_all_setb` / `overlay_hybrid`：先按 2 的幂跨度铺满整张画布，再只覆盖不同色块；所有铺底命令都计入 `R`。
- **切块**：单条 `FILL` 超过 `max_fill_blocks` 时，按行优先切成 2 的幂 tile，必要时退化为 `SETB`。
- **评分**：`R = N_fill·C_fill + N_setb·C_setb`，`J = D + λ·R`；并列按 `(J, D, R, 命令数, 几何签名, 计划名)` 决胜。
- **边界**：`C_fill`、`C_setb`、`λ` 都是配置值，不是服务器实测；当前示例 `λ=16`、`C_fill=1.0`、`C_setb=0.2` 只是演示。

### 3.5 校验优先

写文件前，`TOP.run` 会做一整套一致性检查，任何一项失败都不会写输出：

1. 分区矩形必须完整、无重叠、无越界地覆盖原图。
2. 有序绘图计划重放后必须等于分区图。
3. 由计划重建的 RGB 栅格必须等于分区解码结果。
4. `D` 必须等于按分区复算的 SSE，也必须等于量化 SSE（树聚类不改变颜色）。
5. 序列化命令数必须等于计划命令数；坐标、`FILL` 面积、命令总数必须在限制内。

输出采用"同目录临时文件 + `fsync` + `os.replace`"原子替换，避免半截文件。

### 3.6 双输出：文本给桥接器，JSON 给验证

- `commands.txt`：桥接器唯一需要的输入，语法与 `PLOT_INTERFACE` 完全兼容。
- `image.plt.json`：`plt-block-codec` v1，自包含图像尺寸、调色板、分区、完整操作序列、坐标映射、限制和评分；可解码回 BMP 与命令，用于复现/审计。
- `summary.json`：`PLT-TOP-summary-v3`，记录参数、后端、量化/树信息、D/R/J、分区与命令列表，并给出桥接器建议参数。

### 3.7 桥接器独立于编码器

- **选择**：桥接器把文本编译成原版数据包函数，写入存档，游戏内 `/reload` + `/function` 执行；不用 RCON、不模拟键盘。
- **原因**：编码不需要游戏；桥接需要存档目录和命令权限，职责分离。
- **代价**：受 Minecraft 限制——单函数默认 65,536 条命令、单条 `FILL` 默认 32,768 方块、区块必须加载、一次 tick 执行完。
- **版本**：目标固定 Java 26.3，`pack.mcmeta` 数据包格式 121；旧文档中的 Java 1.10+/RCON 说法已废弃。

### 3.8 GPU 策略

- 有可见 CUDA 设备时用 CuPy 做亮度搜索和量化；**不静默回退**，GPU 运算失败直接报错。
- 没有设备/驱动不可见时用 NumPy；树聚类、RDO、写文件始终在 CPU。
- 只使用 CuPy 高层数组 API，没有自写 CUDA kernel。

## 4. 模块地图（R_002/PLT）

| 文件 | 职责 | 关键入口 |
|---|---|---|
| `PLT/model.py` | 共享不可变数据模型 | `RGBImage`、`PaletteEntry`、`Rect`、`Candidate`、`DrawOp`、`DrawPlan` |
| `PLT/READ_SOURCE/` | BMP/PNG 统一读入 | `read_image`、`write_bmp` |
| `PLT/D/sse.py` | 积分图与 SSE | `IntegralImage`、`sse_candidate`、`reconstruct_candidate` |
| `PLT/TOP/quantizer.py` | 亮度搜索 + 羊毛量化（CuPy/NumPy） | `quantize_to_palette` |
| `PLT/DIV/division.py` | 量化标签图的二叉/四叉树聚类 | `cluster_quantized_pixels` |
| `PLT/R/draw.py` | 生成绘图计划（all_fill/all_setb/hybrid/overlay） | `generate_plans` |
| `PLT/RDO/optimize.py` | 按 `J = D + λR` 选候选/计划 | `select_candidate` |
| `PLT/TOP/plt_top.py` | 主编排、校验、原子写输出 | `run`、`main` |
| `PLT/TOP/configuration.py` | 严格 JSON 配置解析 | `load_config` |
| `PLT/TOP/plt_codec.py` | 编码/解码 CLI | `encode`、`decode` |
| `PLT/bitstream.py` | `plt-block-codec` v1 读写与校验 | `create_stream`、`decode_stream`、`commands_text` |

历史/备用（不在 R_002 主链路）：

- `PLT/DIV/segmentation.py`：CPU 基线的分割候选；R_002 不使用。
- `PLT/RDO/rdo.py`：CPU 基线的候选/计划搜索；R_002 只通过 `optimize.select_candidate` 使用新入口。
- `PLT/TOP/config.example.json`：模块级模板（`image` 指向 `input.png`），发布包以根目录 `config.example.json` 为准。

## 5. 时间线

| 时间（2026-11-19） | 事件 | 产物/证据 |
|---|---|---|
| 14:02:47 | 工作区 `MC_CODEC` 建立 | 目录创建时间 |
| 14:28:21 / 14:46:32 / 14:47:19 | `PLOT_INTERFACE`、`jre-x64`、`PLT` 目录出现 | 目录创建时间 |
| 14:55:15 | `.minecraft\versions\26.3` 就绪 | 目录时间；HMCL 说明 21:43 |
| 15:00:50 | 桥接器首版 `plot_batch.py` | 文件 mtime；`PLOT_INTERFACE/README.md` 15:04 |
| 15:37:30–15:55:13 | CPU 基线模块落地：`RDO/rdo.py`、`DIV/segmentation.py`、`DIV/model.py`、`PLT/model.py`、`READ_SOURCE/bmp.py`、`bitstream.py`、`R/draw.py`、`models.py` | 文件 mtime |
| 15:57:18 | 首轮文档快照（Iteration 01，CPU 基线状态） | `PLT/PLT.md` |
| 16:06:08 | Iteration 02 接口审计：发现 DIV/RDO 并行模型未接入 TOP、旧文档 RCON/版本描述错误 | `PLT/PLT.md` |
| 16:32:04 | Iteration 03：公共 API/façade 收敛，TOP 重接线 | `PLT/PLT.md` |
| 16:46:24–16:47:51 | 活动模块补齐：`D/sse.py`、`RDO/optimize.py`、`DIV/division.py` | 文件 mtime |
| 16:59:41 | Iteration 05：PNG reader 合入，TOP 改用统一 `read_image` | `PLT/PLT.md`、`PLT/README.md` |
| 17:06:38 | R_002 `TOP/plt_codec.py`（编解码 CLI） | 文件 mtime |
| 17:09:52 | `INTERFACE_AUDIT.md` | 文件 mtime |
| 17:33:10 | 16 色羊毛 `wool_palette.json`（26.3 客户端纹理均值） | 文件 mtime |
| 17:33–17:34 | HMCL 本地配置、存档“新的世界”、游戏目录初始化 | `.hmcl/`、`saves/新的世界/` |
| 17:44:23 | PNG reader 支持 alpha/tRNS，输出前合成白底 | `png.py`；R_001 README Iteration 02 |
| 18:06:43 | 首次启动 26.3；18:14 首次安装数据包（旧 74 行 `run.mcfunction`，140×178 几何） | `.hmcl/logs/2026-11-19T18-06-38.log.xz`、存档 datapacks |
| 18:22:06–18:23:44 | R_001 Iteration 04（`max_splits=256`）、R_001 README | `R_001/README.md` 18:23:44 |
| 18:31:58 | R_002 目录建立（自包含发布副本） | 目录创建时间 |
| 18:38:13 | R_002 Iteration 01：固定亮度 + 候选深度搜索 | `R_002/README.md` |
| 18:41:35 | R_002 `R/draw.py` | 文件 mtime |
| 18:47:33 | R_002 Iteration 02：改为"先量化、再树聚类"，移除补色与人工深度 | `R_002/README.md` |
| 19:12:15 / 19:15:06 / 19:18:44 / 19:26:16 | `DIV/division.py`、`config.example.json`、`TOP/configuration.py`、`TOP/plt_top.py` | 文件 mtime |
| 19:41:35 | Iteration 03：确认全局 Python 3.14.7 指向；NumPy 可见性修复；CuPy 缺 headers 时回退 | `R_002/README.md` |
| 19:45:47 | Iteration 04：安装 CUDA runtime/NVRTC，CuPy 完整跑通；10,521 命令，`D=22,139,519` | `R_002/README.md` |
| 19:48:00–19:48:33 | `quantizer.py`；Iteration 05：移除静默 CPU 回退 | 文件 mtime + README |
| 19:58:14 | Iteration 06：全局 `C:\Python314\python.exe` 验收，删除临时 `.venv` | `R_002/README.md` |
| 21:43:15 | Iteration 07：R_002 配置/输出/桥接说明与 HMCL 启动说明补齐 | `PLT/README.md`、`README_HMCL_Minecraft_26.3.md` |
| 21:45:41 | R_002 README 更新 | 文件 mtime |
| 22:00:38 | R_002 输出重建：`commands.txt` 10,521 行、`summary.json`、`image.plt.json` | 文件 mtime/大小 |
| 22:07–22:30 | 本会话只读分析；HMCL 启动崩溃排查（工作区 ACL/受限令牌，与本包代码无关） | 会话记录 |
| 23:01 之后（本次） | 发布打包：`USAGE.md`、`DESIGN_TIMELINE.md`、MANIFEST、RAR | 本目录 |

## 6. 演进中的纠偏

1. **R_002 Iteration 01 → 02**：从"固定亮度 + 候选深度搜索"改为"先量化、再树聚类"。原因是树只能合并相同标签，否则分区无法精确复原量化图。
2. **R_001 → R_002**：保留 `READ_SOURCE`、16 色羊毛、`SETB`/`FILL` 方言和桥接器；替换分割与 RDO 输入。
3. **Iteration 02 → 03（文档审计）**：发现 `DIV/segmentation.py`、`RDO/rdo.py` 的并行数据模型没有接入 TOP；随后用包级 façade 和 `optimize.select_candidate` 收口，避免"文档说已接入、代码没接"。
4. **GPU 回退策略**：Iteration 03 允许 CuPy 失败后回退 NumPy；Iteration 04/05 依据"有可用 GPU 就必须用 GPU"改为强制 GPU，失败即报错。
5. **桥接方式**：旧文档的 Java 1.10+/RCON 描述被废弃，改为 Java 26.3 原版数据包（pack format 121）。

## 7. 现状与下一步

已验证：

- 示例 168×177，1025 个倍率，`backend=cupy`，10,521 条命令（385 `FILL` + 10,136 `SETB`），`D=22,139,519`、`R=2,412.2`、`J=22,178,114.2`。
- 输出命令与 22:00 的仓库产物逐字节一致；示例运行约 3.8 秒（本机 RTX 5070 Ti）。
- 桥接器已在 26.3 单人存档安装过一次数据包（旧几何），新几何可直接重装。

未完成/边界：

- `C_fill`、`C_setb`、`λ` 未在目标环境标定；`max_fill_blocks`/`max_commands` 是客户端检查值，游戏侧仍有自己的限制。
- 只面向 26.3；换版本需重新核对数据包格式和方块语法。
- PNG 透明度合成白底不可配置；不应用 ICC/gamma/EXIF；不支持 Adam7。
- 没有自动化测试套件；依赖运行时一致性校验。
- `DIV.segmentation` / `RDO.rdo` 仍是未接入主链路的 alternate 实现。

## 8. 复现与核对

```powershell
# 编码
cd PLT\R_002
python -m PLT.TOP.plt_top .\config.example.json

# 解码验证
python -m PLT.TOP.plt_codec decode .\image.plt.json --max-pixels 1048576 `
  --output-bmp .\reconstruction.bmp --commands .\decoded_commands.txt

# 桥接预检
python ..\..\PLOT_INTERFACE\plot_batch.py .\commands.txt --world-dir "<存档目录>" --dry-run
```

发布包内把桥接器换成 `bridge\plot_batch.py`，示例图换成 `examples\002.png`，其余命令相同。
