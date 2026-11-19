> **最高优先级工作范围** 阅读与修改范围仅限当前工作区 C:/Users/GAOTIANJIA/D/MC_CODEC。不要读取工作区之外的路径，也不要搜索父目录、用户目录或其他磁盘；缺失的外部信息标为待定。
>
> **本文排序声明** 先说明 TOP 活动调用和并行 Protocol API 的状态，再列评分、结果与搜索限制。
>
> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | RDO 范围** RDO 算法从 R_001 原样复制；候选只有一份量化后树聚类分区，RDO 只在其绘图计划间择优。
>
> **Iteration 03 | 2026-11-19 16:32:04 +08:00 | 接口收敛任务分配** 本轮仅更新下一轮模块修改指令，不改实现代码、不运行测试。

# RDO：当前集成路径与独立 Protocol API

## TOP v1 公共活动入口

TOP 与 v1 调用方使用 `from PLT.RDO import select_candidate`。包级入口由 `PLT.RDO.optimize.select_candidate` 实现，使用 `PLT.model` 的 Candidate/PaletteEntry/DrawPlan，并通过 `PLT.D`、`PLT.R` 公共门面调用活动实现，不通过 Protocol adapter。

其目标为：

    J = D + lambda * R

在受限 DIV 候选和 R 计划中选择最低评分项。并列项按 D、R、总操作数、稳定几何签名和方案名决胜。此搜索确定、有限，不承诺全局最优。

## 当前参数与结果

TOP 要求明确设置 lambda、costs.fill、costs.setb、分割搜索参数及命令限制。D 是 RGB SSE；R 对 R 产生的实际操作序列按双模单命令成本求和。结果包含候选、计划、D、R、J、候选数和评估计划数。

## 未接入 TOP 的并行 API

PLT.RDO.rdo.py 提供自己的 Raster、PaletteEntry、Rect、SegmentationCandidate、DrawPlan 和 DivModule/DModule/RModule Protocol。它与 v1 的 `PLT.model` 及 `select_candidate` 不可直接替换。该 API 面向已有自有 DIV/D/R 适配器、需要独立评估候选和绘图计划的 Python 调用方；TOP 当前不调用它。包根以明确名称 `optimize_with_modules` 导出它；也可直接从 `PLT.RDO.rdo` 导入 `optimize`。包根不再把 Protocol 函数命名为裸 `optimize`。

若要将 Protocol API 接入 TOP，先定义 PLT.model 与该 API 之间的 adapter 和数据转换，再由 TOP 显式改用该入口。不要在 README 中把两个入口混称。

详细对齐任务见 [TASKS.md](TASKS.md) 与 [接口审计](../INTERFACE_AUDIT.md)。

