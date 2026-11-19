> **最高优先级工作范围** 仅使用当前工作区 `C:\Users\GAOTIANJIA\D\MC_CODEC\PLT\R_002` 内的 R_002 实现和说明。
>
> **排序声明** 先定义活动计划及幂次几何，再说明命令成本、限制拆分和接口边界；迭代日志新到旧。
>
> **R_002 Iteration 02 | 2026-11-19 18:47:33 +08:00 | 量化后聚类** R 接收 DIV 对羊毛量化索引图做 bottom-up 树聚类得到的唯一分区；每项仍为二幂节点。

# R：绘图计划与计费

R 根据 DIV 候选生成有序 FILL / SETB 计划，并按 `N_fill*C_fill + N_setb*C_setb` 计费；RDO 选择 `D + lambda*R` 最小的可行结果。

## R_002 几何约束

- 输入 Candidate 的每个分区宽、高必须是 2 的幂，非幂次矩形直接报错。
- `SETB` 是 `1×1`，符合 2 幂规则。
- 未超过 `max_fill_blocks` 的 FILL 保留原分区尺寸；超过限制时，R 使用不大于限制的 2 幂宽/高瓦片拆分，瓦片整除原矩形，不生成非幂次边缘块。
- 限制拆分后仍按每条 FILL 和 SETB 计费；命令数约束与 TOP 序列化规则一致。

## 接口

活动入口为 `PLT.R.generate_plans(candidate, c_fill, c_setb, max_fill_blocks, max_commands, initial_background_block, canvas_width, canvas_height)`。计划操作维持图像坐标和有序绘制语义；世界坐标映射与文本输出由 TOP 完成。

## 迭代记录（新到旧）

- **Iteration 02 | 2026-11-19 18:47:33 +08:00**：消费量化后树聚类的单个 Candidate；R 的命令成本和 fill/setb 选择语义不变。
- **Iteration 01 | 2026-11-19 18:38:13 +08:00**：Candidate 校验强制宽高为 2 的幂；FILL 限制瓦片改用幂次尺寸。
