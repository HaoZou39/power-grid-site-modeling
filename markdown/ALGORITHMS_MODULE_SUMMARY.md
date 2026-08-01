# Algorithms Module Summary

算法模块当前包含公共多目标组件、CMA-ES、多起点 Adam，以及 VAE-like multi-head 候选生成器。

具体口径分别服从：

- `markdown/ALGORITHM_COMMON.md`：目标顺序、权重、normalization、切比雪夫、Weiszfeld 和 Pareto。
- `markdown/CMA_ES.md`：CMA-ES 搜索流程和输出。
- `markdown/MULTISTART_ADAM.md`：多起点 Adam 搜索流程和输出。
- `VAE_LIKE_MULTIHEAD_ALGORITHM.md`：VAE-like multi-head 的 Gaussian head、重参数化、softmin、训练调度等技术实现来源。
- `markdown/VAE_LIKE_MULTIHEAD_ALGORITHM.md`：将根目录技术方案适配到本项目的实施、评价、输出和执行流程。
- `markdown/VALIDATION.md`：不同算法验证流程共用的等间距偏好 CSV 生成口径。
- `markdown/FIGURES_MODULE_SUMMARY.md`：公共 figure 输出。

算法模块不读取原始 tif/csv/GeoJSON，不重新实现建模目标。数据读取由 `data_tools/` 完成，目标和 hard metrics 由 `modeling/` 完成。
