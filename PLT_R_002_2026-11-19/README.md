# PLT R_002 发布包（Minecraft Java 26.3 羊毛绘图）

- 打包时间：2026-11-19（本机，UTC+8）
- 来源：仓库 `PLT/R_002` 的自包含发布副本；示例输出由包内 `config.example.json` 重新生成
- 适用版本：Minecraft Java **26.3**（数据包格式 121）

## 这是什么

把 BMP/PNG 量化成 16 色羊毛，再用树聚类和 RDO 生成有序的 `SETB` / `FILL` 指令文件：

```text
BMP/PNG → 亮度搜索 + 羊毛量化 → 二叉/四叉树同色聚类 → RDO → commands.txt
commands.txt → bridge/plot_batch.py → 存档数据包 → /reload → /function plot_interface:run
```

编码器在本地生成文件，不连接游戏、不修改世界；桥接器只写存档里的数据包，不使用 RCON。

## 快速开始

需要 Python（本机验收 3.14.7）和 NumPy：

```powershell
python -m pip install -r requirements.txt
cd PLT_R_002_2026-11-19
python -m PLT.TOP.plt_top .\config.example.json
```

生成：

| 文件 | 说明 |
|---|---|
| `out\commands.txt` | 10,521 行 `SETB` / `FILL` |
| `out\summary.json` | 参数、量化/树信息、D/R/J、分区与命令列表 |
| `out\image.plt.json` | 可解码的 PLT v1 流 |

示例图 168×177，使用 CuPy 时约 3.8 秒（本机 RTX 5070 Ti）；没有 GPU 时会用 NumPy。

可选 GPU 依赖：

```powershell
python -m pip install -r requirements-gpu-cupy13x.txt
```

## 目录

```text
PLT_R_002_2026-11-19\
├─ README.md                 本文件
├─ USAGE.md                  完整使用说明（配置、输出、桥接、排错）
├─ DESIGN_TIMELINE.md        代码成型思路与时间线
├─ MANIFEST.sha256           文件校验和
├─ config.example.json       包内示例配置（指向 examples\002.png）
├─ wool_palette.json         16 色羊毛 RGB 与来源元数据
├─ requirements.txt          CPU 依赖
├─ requirements-gpu-cupy13x.txt  GPU 依赖
├─ PLT\                      编码器代码（READ_SOURCE / D / DIV / R / RDO / TOP）
├─ bridge\
│  ├─ plot_batch.py          桥接器（与仓库 PLOT_INTERFACE\plot_batch.py 相同）
│  └─ commands.example.txt   桥接器最小示例
└─ examples\
   ├─ 002.png                示例输入
   └─ expected\              示例输出（commands / summary / image.plt.json）
```

## 在 Minecraft 里使用

1. 找到含 `level.dat` 的单人存档目录，确认世界允许命令。
2. 预检（不写存档）：

   ```powershell
   python .\bridge\plot_batch.py .\examples\expected\commands.txt --world-dir "<存档目录>" --dry-run
   ```

3. 去掉 `--dry-run` 再执行，安装数据包。
4. 进入世界执行：

   ```text
   /reload
   /function plot_interface:run
   ```

注意事项：命令只影响已加载区块；整个函数在一个 tick 内执行完，会有明显卡顿；`FILL` 默认覆盖区域内方块；没有内置撤销。详见 [USAGE.md](USAGE.md) 第 7 节。

## 与仓库版本的关系

- 包内 `PLT\` 与仓库 `PLT\R_002\PLT\` 相同（已剔除 `__pycache__`）。
- 包内 `config.example.json` 改成相对路径，输出到 `out\`；仓库版本使用绝对图片路径、输出在 R_002 根目录。
- `examples\expected\commands.txt` 与 `examples\expected\image.plt.json` 和仓库 2026-11-19 22:00 的产物逐字节一致；`summary.json` 只有 `config`/`input` 的绝对路径不同。
- 桥接器与示例图是从仓库 `PLOT_INTERFACE`、`PLT\REFERENCE_FIG` 复制进包的，方便脱离仓库直接使用。

## 校验

```powershell
Get-FileHash -Algorithm SHA256 .\examples\expected\commands.txt
Get-FileHash -Algorithm SHA256 .\examples\expected\image.plt.json
```

与 `MANIFEST.sha256` 对照；完整文件清单和哈希都在其中。

## 边界

- `lambda`、`C_fill`、`C_setb` 是配置值，不是目标环境实测成本。
- 只面向 Java 26.3；换版本需重新核对数据包格式与方块语法。
- PNG 透明度统一合成白底；不支持 Adam7、ICC/gamma/EXIF 色彩管理。
- 没有自动化测试套件；运行时有一致性校验兜底。

更多说明见 [USAGE.md](USAGE.md) 与 [DESIGN_TIMELINE.md](DESIGN_TIMELINE.md)。
