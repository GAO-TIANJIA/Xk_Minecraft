> **最高优先级工作范围** 阅读与修改范围仅限当前工作区 C:/Users/GAOTIANJIA/D/MC_CODEC。不要读取工作区之外的路径，也不要搜索父目录、用户目录或其他磁盘；缺失的外部信息标为待定。
>
> **本文排序声明** 先解决 optimize 命名冲突，再列活动评分接口、并行 API 隔离和结果要求；迭代日志新到旧。
>
> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | 集成状态** RDO 逻辑保持 R_001 不变；候选由量化索引图唯一决定，D 是全局倍率下的羊毛量化 SSE。
>
> **Iteration 04 | 2026-11-19 | P0 公共入口收敛** 已完成包级命名、TOP 导入路径及活动 RDO 对 D/R 公共门面的调整；未运行测试。

# RDO：任务分配与公共评分接口

## 当前活动实现

TOP 使用 `from PLT.RDO import select_candidate`；实现位于 RDO/optimize.py，以 PLT.model 为类型，经 `PLT.D` 和 `PLT.R` 公共门面调用 D/R。目标为 J = D + lambda * R，有限候选内确定性择优。

## 已完成的 P0 接口收敛

### P0：消除包级 optimize 名称冲突

1. `PLT.RDO.select_candidate` 是 TOP v1 公共评分入口，导出自 RDO/optimize.py。
2. `PLT.RDO.rdo.optimize` 保留为独立 Protocol API，包级显式别名为 `optimize_with_modules`；包根不导出裸 Protocol `optimize`。
3. TOP 使用 `from PLT.RDO import select_candidate`。
4. README 区分公共 v1 入口与 Protocol API，并说明 Protocol API 的目标调用方及 adapter 接入要求。
5. 活动 optimize.py 经 `PLT.D`、`PLT.R` 公共门面调用 D/R。

## 后续维护要求

### P1：锁定评分和结果模型

- 所有 v1 分数以 PLT.model Candidate/PaletteEntry/DrawPlan 计算；lambda、C_fill、C_setb 由 TOP 配置传入。
- SelectedResult 的 D、R、J、方案、操作数与 R 输出的同一操作列表对应。
- 并列顺序保持确定性，有限候选搜索不承诺全局最优。
- Protocol API 如需接入 v1，先写 adapter 和转换契约；未适配前保持隔离。

## 本模块完成条件

包级 import 名无冲突；TOP 从稳定公共入口取得 select_candidate；任一 API 的数据类型不会未经转换混入另一条链路；RDO 不重新定义 D/R 语义。

## 迭代记录（新到旧）

- Iteration 03 | 2026-11-19 16:32:04 +08:00：分配 RDO 包级命名收敛与公共入口；无代码变更。
- Iteration 02 | 2026-11-19 16:06:08 +08:00：确认 optimize.py 活动路径与 rdo.py Protocol API 冲突。

