> **最高优先级工作范围** 阅读与修改范围仅限当前工作区 C:/Users/GAOTIANJIA/D/MC_CODEC。不要读取工作区之外的路径，也不要搜索父目录、用户目录或其他磁盘；缺失的外部信息标为待定。
>
> **本文排序声明** 先列需要修正的接口/类型缺陷，再列统一模型、兼容路径和完成条件；迭代日志新到旧。

> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | 集成状态** D/SSE 实现继承 R_001；亮度倍率影响羊毛标签选择，但 D 以未缩放原图为误差参考，底向上聚类保持标签不变。
>
> **Iteration 04 | 2026-11-19 | P0/P1 接口收敛** 已修正可解析注解、增加 `PLT.D` 公共门面并切换 TOP/RDO 导入；遵照本轮指令未运行测试。
>
> **Iteration 03 | 2026-11-19 16:32:04 +08:00 | 下一轮接口收敛分配** 本轮只写任务与修改指令，不改实现代码、不运行测试。

# D：任务分配与 SSE 接口

## 当前活动接口

D 以 PLT.model.RGBImage、Candidate、PaletteEntry 为主路径。IntegralImage(image) 建表；sse_candidate(candidate, palette_map, integral) 返回 RGB SSE；reconstruct_candidate 物化完整 RGB 栅格。

## 已完成修改

- `reconstruct_candidate` 的调色板类型注解现解析为 `PLT.model.PaletteEntry`；`IntegralImage` 与栅格参考 SSE 的图像注解也统一为 `PLT.model.RGBImage`。
- `PLT.D` 包级导出活动接口；TOP/RDO 从该门面导入。

## 后续明确修改指令

### P0：修正可解析类型注解（已完成）

现有文档记录 reconstruct_candidate 的 palette 注解引用未导入的 PaletteEntry。下一轮修改 D/sse.py：显式导入并限定为 PLT.model.PaletteEntry，或使用等价的模块限定注解；确保运行时类型提示求值能够解析。不得改变 SSE 数值或绘制行为。

### P1：建立唯一活动 D façade（已完成）

1. 在 PLT.D 包级导出 IntegralImage、SSEError、sse_candidate、reconstruct_candidate 和 sse_reconstruction；TOP/RDO 改为从公共门面导入活动接口。
2. 所有活动函数以 PLT.model 为唯一主数据模型；不要将 PLT.DIV.model.Rect 或 PLT.RDO.rdo.Rect 加入主签名。
3. PLT.models.Segment/RgbImage 辅助函数保留为兼容层；仅留在 `PLT.D.sse`，不从 `PLT.D` 包级门面导出，不让其成为 TOP 活动接口。

### P2：约束 SSE 语义

- D 是原始 RGB8 三通道平方误差和，返回非负整数；不归一化、不包含 alpha。
- D 与 DIV 的代表 RGB、TOP JSON 解码的重建 RGB 必须使用同一 palette。
- 若未来改变色差/alpha 规则，另定码流版本或显式 profile；不静默改变 v1 含义。

## 本模块完成条件

类型注解可解析；包级接口对象与 TOP 主链路对象一致；分割直接路径、重建栅格路径的 D 定义保持同一语义；旧辅助几何不会被误当作主路径类型。

## 迭代记录（新到旧）

- Iteration 04 | 2026-11-19：完成类型注解收敛和 `PLT.D` 公共门面；TOP/RDO 已迁移；未运行测试。
- Iteration 03 | 2026-11-19 16:32:04 +08:00：分配注解修正与 D 公共 façade；无代码变更。
- Iteration 02 | 2026-11-19 16:06:08 +08:00：记录 PLT.model 活动路径及旧辅助类型边界。

