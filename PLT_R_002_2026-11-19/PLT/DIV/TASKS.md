> **最高优先级工作范围** 仅在当前工作区 `C:\Users\GAOTIANJIA\D\MC_CODEC` 内读取/修改；R_002 DIV 实现位于本版本目录。
>
> **排序声明** 按接口、树规则、像素覆盖/误差不变量排列；迭代记录新到旧。
>
> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | 实施状态** DIV 改为只接收已量化的 wool index image；无候选搜索深度。

# DIV：R_002 接口与实现要求

## 活动签名

`cluster_quantized_pixels(width, height, palette, pixel_indices, integral) -> tuple[Candidate, ...]`

## 硬性要求

1. 颜色数量不要求是 2 的幂，DIV 不补充/重排 palette。
2. 内部树宽/高分别补到最近的 2 的幂，外部哨兵节点绝不成为像素或命令。
3. 递归从完整像素单元开始；两轴均大于 1 时四叉，一轴为 1 时沿另一个轴二叉，直到 1×1。
4. 自下而上仅合并标签相同的有效兄弟；不得合并不同 wool block_id，不允许聚类改变 TOP 量化结果。
5. 输出最大同色节点，必须精确覆盖原图、无重叠，且每块只引用输入 palette。
6. 不设 `max_splits`、`candidate_limit`、`split_positions_per_axis` 或其他人工分割深度。

## 已实施

- `division.py` 使用 NumPy 整数/布尔层数组完成二叉/四叉 bottom-up 标记；返回唯一完整的 Candidate。
- Candidate 失真用亮度优化后 RGB 的 IntegralImage 重算，TOP 复核 D 与全局量化 SSE 相等。
- Alternate `segmentation.py` 保持隔离，不进入活动接口。

## 迭代记录（新到旧）

- **Iteration 02 | 2026-11-19 18:47:33 +08:00**：废止 Iteration 01 的候选搜索，换成量化索引二/四叉树底向上聚类。
- **Iteration 01 | 2026-11-19 18:38:13 +08:00**：曾按 2 幂宽高做深度受限切分，已废止。
