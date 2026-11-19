> **最高优先级工作范围** R_002 R 模块的实现/文档仅位于当前工作区 `C:\Users\GAOTIANJIA\D\MC_CODEC\PLT\R_002`。
>
> **排序声明** 按重要性列出几何接口约束、FILL 切分与计费，再列迭代历史；历史从新到旧。
>
> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | 已实施** 计划来自羊毛索引图的唯一树聚类 Candidate；保持每个树节点及拆分 FILL 的幂次几何。

# R：R_002 任务状态

## 活动契约

1. `PLT.R.generate_plans` 只接受 `PLT.model.Candidate`；每个 Rect 的 width/height 都必须是正的 2 的幂。
2. `SETB` 几何固定为 1×1。FILL 几何宽高均为 2 的幂，包括因 `max_fill_blocks` 限制拆分出的子命令。
3. 每个子命令按一次执行计费；`R = N_fill*C_fill + N_setb*C_setb`。成本常数仍由配置给出。
4. 绘图计划逐矩形保留顺序，TOP 不重新合并出非幂次的 FILL。

## 已实施修改

- `_validate_candidate` 拒绝宽/高非 2 幂的矩形。
- `_fill_tile_size` 选择面积不超过 `max_fill_blocks` 的最大幂次瓦片宽高。幂次分区尺寸由幂次瓦片整除，避免不规则边缘瓦片。
- `max_fill_blocks=0` 仍表示不限制；整块 FILL 仍保持候选矩形的幂次几何。

## 迭代记录（新到旧）

- **Iteration 02 | 2026-11-19 18:47:33 +08:00**：RDO 不再跨分区候选搜索；继续比较同一量化分区的 FILL/SETB 计划。
- **Iteration 01 | 2026-11-19 18:38:13 +08:00**：完成幂次几何校验和限制 FILL 的幂次拆分。
