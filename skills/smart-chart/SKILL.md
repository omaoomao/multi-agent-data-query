---
name: smart-chart
description: 根据数据特征智能选择最佳图表类型并生成 ECharts 配置。当用户要求"画图"、"生成图表"、"可视化"、"对比图"、"趋势图"时使用此 skill。
---

# 智能图表生成

根据数据的维度、数值特征和用户意图，自动选择最合适的图表类型，生成 ECharts 配置。

## 图表选择决策树

根据数据特征选择图表类型：

```
数据只有1个维度 + 1个数值 → 看用户意图
  ├─ "占比/比例/构成" → 饼图 pie
  ├─ "排名/对比/多少" → 柱状图 bar
  └─ "趋势/变化/走势" → 折线图 line

数据有1个维度 + 多个数值 →
  ├─ "对比各项" → 分组柱状图 bar (grouped)
  ├─ "占比构成" → 堆叠柱状图 bar (stacked)
  └─ "趋势对比" → 多条折线图 line (multiple series)

数据有时间维度 (年/月/季度) → 折线图 line（首选）
  ├─ 同时要对比 → 多条折线图
  └─ 同时要看占比 → 面积图 line (areaStyle)

数据是2个数值维度 → 散点图 scatter

数据要展示排名 → 横向柱状图 bar (horizontal, yAxis为类目)
```

## 常用图表模板

### 1. 柱状图（排名/对比）

适用于：各专业就业率对比、各学院招生人数对比

```json
{
  "title": {"text": "各专业就业率对比", "left": "center"},
  "tooltip": {"trigger": "axis", "formatter": "{b}: {c}%"},
  "grid": {"left": "10%", "right": "5%", "bottom": "15%"},
  "xAxis": {
    "type": "category",
    "data": ["软件工程", "计算机科学", "人工智能", "数据科学", "信息安全"],
    "axisLabel": {"rotate": 30, "fontSize": 11}
  },
  "yAxis": {
    "type": "value",
    "name": "就业率(%)",
    "min": 80,
    "max": 100
  },
  "series": [{
    "type": "bar",
    "data": [96.5, 95.2, 97.8, 94.1, 93.6],
    "itemStyle": {
      "color": {
        "type": "linear",
        "x": 0, "y": 0, "x2": 0, "y2": 1,
        "colorStops": [
          {"offset": 0, "color": "#4facfe"},
          {"offset": 1, "color": "#00f2fe"}
        ]
      },
      "borderRadius": [4, 4, 0, 0]
    },
    "label": {"show": true, "position": "top", "formatter": "{c}%"}
  }]
}
```

### 2. 折线图（趋势/变化）

适用于：某专业历年就业率趋势、招生人数变化

```json
{
  "title": {"text": "软件工程专业就业率趋势", "left": "center"},
  "tooltip": {"trigger": "axis"},
  "grid": {"left": "10%", "right": "5%", "bottom": "10%"},
  "xAxis": {
    "type": "category",
    "data": ["2020", "2021", "2022", "2023", "2024"],
    "boundaryGap": false
  },
  "yAxis": {
    "type": "value",
    "name": "就业率(%)",
    "min": 85,
    "max": 100
  },
  "series": [{
    "type": "line",
    "data": [91.2, 93.5, 94.8, 95.6, 96.5],
    "smooth": true,
    "lineStyle": {"width": 3, "color": "#4facfe"},
    "itemStyle": {"color": "#4facfe"},
    "areaStyle": {
      "color": {
        "type": "linear",
        "x": 0, "y": 0, "x2": 0, "y2": 1,
        "colorStops": [
          {"offset": 0, "color": "rgba(79,172,254,0.3)"},
          {"offset": 1, "color": "rgba(79,172,254,0.02)"}
        ]
      }
    },
    "label": {"show": true, "formatter": "{c}%"}
  }]
}
```

### 3. 多系列折线图（趋势对比）

适用于：多个专业就业率对比趋势

```json
{
  "title": {"text": "各专业就业率趋势对比", "left": "center"},
  "tooltip": {"trigger": "axis"},
  "legend": {"data": ["软件工程", "计算机科学", "人工智能"], "bottom": 0},
  "grid": {"left": "10%", "right": "5%", "bottom": "15%"},
  "xAxis": {
    "type": "category",
    "data": ["2020", "2021", "2022", "2023", "2024"],
    "boundaryGap": false
  },
  "yAxis": {"type": "value", "name": "就业率(%)"},
  "series": [
    {"name": "软件工程", "type": "line", "data": [91.2, 93.5, 94.8, 95.6, 96.5], "smooth": true},
    {"name": "计算机科学", "type": "line", "data": [90.1, 91.8, 93.2, 94.5, 95.2], "smooth": true},
    {"name": "人工智能", "type": "line", "data": [88.5, 92.3, 95.1, 96.8, 97.8], "smooth": true}
  ]
}
```

### 4. 饼图（占比/构成）

适用于：各学院招生人数占比、学历构成

```json
{
  "title": {"text": "2024年各学院招生人数占比", "left": "center"},
  "tooltip": {"trigger": "item", "formatter": "{b}: {c}人 ({d}%)"},
  "legend": {"orient": "vertical", "left": "left", "top": "middle"},
  "series": [{
    "type": "pie",
    "radius": ["40%", "70%"],
    "center": ["55%", "55%"],
    "avoidLabelOverlap": true,
    "itemStyle": {"borderRadius": 6, "borderColor": "#fff", "borderWidth": 2},
    "label": {"show": true, "formatter": "{b}\n{d}%"},
    "data": [
      {"value": 520, "name": "计算机学院"},
      {"value": 380, "name": "电子信息学院"},
      {"value": 290, "name": "管理学院"},
      {"value": 210, "name": "外语学院"},
      {"value": 180, "name": "艺术学院"}
    ]
  }]
}
```

### 5. 分组柱状图（多维度对比）

适用于：各专业招生人数 vs 就业人数对比

```json
{
  "title": {"text": "各专业招生与就业人数对比", "left": "center"},
  "tooltip": {"trigger": "axis"},
  "legend": {"data": ["招生人数", "就业人数"], "bottom": 0},
  "grid": {"left": "10%", "right": "5%", "bottom": "15%"},
  "xAxis": {
    "type": "category",
    "data": ["软件工程", "计算机科学", "人工智能", "数据科学"]
  },
  "yAxis": {"type": "value", "name": "人数"},
  "series": [
    {
      "name": "招生人数",
      "type": "bar",
      "data": [120, 150, 80, 60],
      "itemStyle": {"color": "#4facfe"}
    },
    {
      "name": "就业人数",
      "type": "bar",
      "data": [115, 143, 78, 56],
      "itemStyle": {"color": "#43e97b"}
    }
  ]
}
```

### 6. 横向柱状图（排名）

适用于：薪资排名、就业率排名

```json
{
  "title": {"text": "各专业平均起薪排名", "left": "center"},
  "tooltip": {"trigger": "axis", "formatter": "{b}: {c}元"},
  "grid": {"left": "15%", "right": "10%", "bottom": "5%"},
  "yAxis": {
    "type": "category",
    "data": ["信息安全", "人工智能", "计算机科学", "软件工程", "数据科学"],
    "inverse": true
  },
  "xAxis": {"type": "value", "name": "平均起薪(元)"},
  "series": [{
    "type": "bar",
    "data": [12500, 11800, 10500, 9800, 9200],
    "itemStyle": {
      "color": {
        "type": "linear",
        "x": 0, "y": 0, "x2": 1, "y2": 0,
        "colorStops": [
          {"offset": 0, "color": "#fa709a"},
          {"offset": 1, "color": "#fee140"}
        ]
      },
      "borderRadius": [0, 4, 4, 0]
    },
    "label": {"show": true, "position": "right", "formatter": "{c}元"}
  }]
}
```

## 配色方案

招生就业场景推荐色板：

```python
COLOR_PALETTE = [
    "#4facfe",  # 蓝 - 主色
    "#43e97b",  # 绿 - 正面指标
    "#fa709a",  # 粉 - 需关注
    "#fee140",  # 黄 - 警示
    "#a18cd1",  # 紫 - 辅助
    "#fbc2eb",  # 浅粉
    "#f6d365",  # 金
    "#89f7fe",  # 青
]
```

使用时在 ECharts 配置中添加：
```json
{
  "color": ["#4facfe", "#43e97b", "#fa709a", "#fee140", "#a18cd1"]
}
```

## 图表选择速查表

| 数据特征 | 推荐图表 | ECharts type |
|---------|---------|-------------|
| 各项对比/排名 | 柱状图 | `bar` |
| 时间趋势 | 折线图 | `line` |
| 多项趋势对比 | 多系列折线 | `line` (多个 series) |
| 占比构成 | 饼图/环形图 | `pie` |
| 多维度对比 | 分组柱状图 | `bar` (多个 series) |
| 排名展示 | 横向柱状图 | `bar` (yAxis 为类目) |
| 分布关系 | 散点图 | `scatter` |

## 注意事项

- 图表标题必须用中文
- 百分比数据在 tooltip 和 label 中显示 `%` 后缀
- 类目名称过长时 xAxis label 加 `rotate: 30`
- 数据超过 10 个类目时考虑用横向柱状图
- 饼图数据项不超过 8 个，超过的归入"其他"
