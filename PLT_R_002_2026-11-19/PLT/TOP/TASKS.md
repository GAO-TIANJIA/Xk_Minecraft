> **最高优先级工作范围** 仅在当前工作区 `C:\Users\GAOTIANJIA\D\MC_CODEC` 内修改；R_002 的 TOP 代码、配置和文档在本版本目录。
>
> **排序声明** 先列处理顺序与量化/聚类不变量，再列 GPU 环境、输出接口及迭代历史。
>
> **R_002 Iteration 06 | 2026-11-19 19:58:14 +08:00 | 已实施** 使用全局 `C:\Python314\python.exe` 启动；不依赖项目虚拟环境。已在示意图配置上确认 NumPy/CuPy/GPU 并完成编码。
>
> **最高优先级工作范围** 仅在当前工作区 `C:\Users\GAOTIANJIA\D\MC_CODEC` 内读取和修改。
>
> **排序声明** 先列处理顺序与量化/聚类不变量，再列依赖和后端回退，迭代历史新到旧。

# TOP：R_002 实施任务与接口

## 固定处理顺序

1. READ_SOURCE 解码 RGB8；不在 reader 中改亮度。
2. 对 `brightness_scale="auto"` 构造含端点的全局倍率网格；每个倍率仅控制像素选择哪个 palette label，目标 SSE 始终比较未缩放原 RGB 与所选羊毛 RGB。用户可将 scale 设为数值固定倍率。
3. 将原 RGB8 和 palette 索引图交给 TOP/D；将 palette 索引图交给 DIV 做树聚类。
4. 聚类只合并相同 palette 索引；D 总误差应等于量化器的全图 SSE；R/RDO 不再尝试其他图像颜色或分割候选。
5. 序列化 SETB/FILL 并校验完整覆盖、命令数量、方块限制和 Minecraft 坐标。

## 配置

- palette 严格保持调用方原有内容和顺序；不需要 2 幂数量、不自动补色。
- 默认 brightness search 为 `[0,4]` 的 1025 点均匀网格；通过 `brightness_search` 可配置 min/max/steps，steps 含端点且为 2–4097。
- R_001 的 `search` 字段可在读取旧配置时忽略；不再影响分割或生成候选数。
- `numpy` 用于 CPU 回退和树数组；可用 CuPy 时以高层数组运算在 GPU 并行量化；无自写 CUDA kernel/指令。
- 已检测到可用 GPU 时，必须完成 CuPy 运算并报告 `backend=cupy`；GPU 运算异常直接报错，不静默改用 CPU。只有没有可用 GPU/驱动时才允许 CPU 运行。部署 GPU 环境需安装 `requirements-gpu-cupy13x.txt`，其中包含 CuPy CUDA 13.x 与 CUDA runtime/NVRTC 组件。
- 依赖必须对启动 TOP 的 Windows 用户可见；共享 Python 的用户 site-packages 按 Windows 用户隔离。`C:\Python314\python.exe` 的解释器选择本身不保证包对所有账户可见。
- 当前已验证的全局解释器命令为 `C:\Python314\python.exe -m PLT.TOP.plt_top .\config.example.json`。缺包时应由运行该解释器的 Windows 用户执行 `C:\Python314\python.exe -m pip install --user -r requirements-gpu-cupy13x.txt`。

## 已完成的代码接口

- `TOP.quantizer.quantize_to_palette` 返回最佳倍率、调整 RGB、palette 索引、SSE、后端和评估倍率数。
- `DIV.cluster_quantized_pixels` 返回唯一的 bottom-up 聚类候选。
- 摘要记录量化搜索和后端；PLT JSON score 添加倍率/后端元数据，version 1 主体不变。

## 迭代记录（新到旧）

- **Iteration 06 | 2026-11-19 19:58:14 +08:00**：使用全局 Python 3.14.7 (`C:\Python314\python.exe`) 运行示意图配置，CuPy 在 RTX 5070 Ti 上量化，输出 10,521 条指令；本轮创建的 `.venv` 已删除。
- **Iteration 05 | 2026-11-19 19:48:33 +08:00**：按用户 GPU 要求移除设备可见时的静默 CPU 回退；CuPy 设备计数成功后，完整量化固定使用 GPU。
- **Iteration 04 | 2026-11-19 19:45:47 +08:00**：响应用户“有能用的 GPU 时一定要能用 GPU”。安装 CUDA runtime/NVRTC 13.5.37 Python wheels；CuPy 百万元素计算通过，R_002 编码最终摘要 `backend=cupy`。
- **Iteration 03 | 2026-11-19 19:41:35 +08:00**：依据用户终端截图确认 Python 3.14.7 指向 `C:\Python314\python.exe`，但进程账户的 NumPy 不可见。将 NumPy 2.5.5、CuPy 14.2.0、cuda-pathfinder 1.9.1 安装到 `C:\Users\GAOTIANJIA\AppData\Roaming\Python\Python314\site-packages`。由于 CuPy 缺 CUDA headers，增加运行期异常的 NumPy 回退；完整 R_002 编码需在当前迭代重新核验。
- **Iteration 02 | 2026-11-19 18:47:33 +08:00**：删除颜色补齐和人工分割深度；自动量化亮度后树聚类；使用已安装的 NumPy/CuPy。
- **Iteration 01 | 2026-11-19 18:38:13 +08:00**：幂次矩形切分方案被用户澄清替换。
