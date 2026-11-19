# 桥接器（PLOT_INTERFACE 副本）

`plot_batch.py` 把 `SETB` / `FILL` 文本编译成 Minecraft Java 26.3 单人世界的数据包函数。它与仓库 `PLOT_INTERFACE\plot_batch.py` 相同，复制进本包只是为了脱离仓库直接使用。

## 用法

```powershell
# 预检：只校验并打印编译结果，不写存档
python .\bridge\plot_batch.py .\examples\expected\commands.txt --world-dir "<含 level.dat 的存档目录>" --dry-run

# 安装/更新数据包
python .\bridge\plot_batch.py .\examples\expected\commands.txt --world-dir "<含 level.dat 的存档目录>"
```

然后在游戏里执行：

```text
/reload
/function plot_interface:run
```

## 输入格式

```text
SETB x y z block
FILL x1 y1 z1, x2 y2 z2 block
```

绝对整数坐标；`FILL` 两端点包含；方块名使用 26.3 风格（名称 + 可选状态）。空行与 `#`、`//` 注释会被忽略。

## 选项

- `--world-dir`：必填，必须包含 `level.dat`。
- `--max-blocks N`：单条 `FILL` 最大方块数，默认 32768；`0` 表示不做脚本侧限制。
- `--max-commands N`：函数最大命令数，默认 65536；`0` 表示不做脚本侧限制。
- `--dry-run`：只校验并打印，不写入。

脚本只覆盖带 `.plot_interface_generated` 标记的数据包；数据包写入 `<存档>\datapacks\plot_interface`，函数在 `data\plot_interface\function\run.mcfunction`。

## 注意

- 只面向 Java 26.3 单人世界；不是 RCON，也不是基岩版 `/wsserver`。
- 命令只影响已加载区块；整个函数在一个 tick 内执行。
- 详细说明见仓库 `PLOT_INTERFACE\README.md`。
