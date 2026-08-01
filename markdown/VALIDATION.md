# 多目标偏好验证集 CSV

验证集单独放在：

```text
validation_data/
  preferences_step_0.1.csv
```

CSV 字段：

```csv
preference_id,weight_dem,weight_road,weight_demand
```

三个权重按固定步长在单纯形上等间距生成，并满足：

```text
weight_dem >= 0
weight_road >= 0
weight_demand >= 0
weight_dem + weight_road + weight_demand = 1
```

默认步长为 `0.1`。令 `n = 1 / step = 10`，按以下方式枚举：

```text
i = 0...n
j = 0...(n-i)
k = n-i-j

weight_dem = i/n
weight_road = j/n
weight_demand = k/n
```

步长 `0.1` 共生成 66 条偏好：

```text
(n+1)(n+2)/2 = 66
```

示例：

```csv
preference_id,weight_dem,weight_road,weight_demand
0,0.0,0.0,1.0
1,0.0,0.1,0.9
2,0.0,0.2,0.8
```

生成脚本单独放置：

```text
validation_data/build_preferences.py
```

脚本只负责按给定 step 生成对应文件名的 CSV，例如 `step=0.1` 输出 `preferences_step_0.1.csv`。该偏好文件由不同算法的验证流程共用，不属于 VAE-like 专属数据。训练代码不使用这份 CSV；验证时只读取该文件。
