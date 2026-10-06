# 风洞压力轨迹约简工具

轻量全栈工具：粘贴风洞试验压力轨迹 JSON，两种求解模式共用同一份整数/有理数精确判定，
无浮点舍入。

* **阈值模式（旧）**：`POST /api/simplify`。求一条**保留点数量最少**的折线，使相邻保留点
  之间每个原始点到线性插值的纵向偏差不超过整数 `tolerance`；点数相同时取下标序列
  **字典序最小**的解。
* **段数预算模式（新）**：`POST /api/simplify-budget`。给定段数上限 `budget`（1–10 且
  小于采样点数），先最小化全程最大纵向偏差（**约分有理数**），再在同一偏差下使用最少段，
  最后取保留下标序列字典序最小者；每段额外返回达到段内最坏偏差的**最小原始下标**作为可
  复核见证。预算结果由真实偏差直接求得，**不**由旧整数 tolerance 结果四舍五入凑出。

## 问题定义

输入：2–120 个采样点 `{time, value}`，`time` 为 `[0, 10^9]` 内严格递增整数，
`|value| <= 10^6`。阈值模式下 `tolerance` 为 `[0, 10^6]` 整数；预算模式下 `budget`
为 `[1, 10]` 整数且严格小于采样点数。

对保留段 `i -> j`，中间点 `k` 的纵向偏差为

```
|(v_k - v_i) * (t_j - t_i) - (v_j - v_i) * (t_k - t_i)| / (t_j - t_i)
```

阈值模式把不等式两边乘以正数 `(t_j - t_i)` 做**整数交叉相乘**判定
（`api/app/simplifier.py` 的 `within_segment`）；预算模式用 `fractions.Fraction`
保存该偏差的**约分形式**，比较时同样是整数交叉相乘（`vertical_deviation`），不使用
除法或浮点数。

## 求解思路（预算模式）

1. 预算计算每一条可能的段 `i -> j` 的代价（段内最大偏差，`Fraction`）与见证下标
   （并列时取最小下标）。
2. 最优全程偏差必等于某条段的代价：把所有段代价去重排序后二分，可行性判定是“DAG 上
   是否存在边数 ≤ budget、每边代价 ≤ 候选值的 0→n-1 路径”（逆序 DP）。
3. 找到最优偏差后，在对应可达图上再做一次逆序最短路 DP（同偏差下最少段），正向重建时
   在所有仍在最短路上的后继里取最小下标，得到字典序最小解。
4. 零误差（共线）、并列最优、分母不为 1 的非整数最优值均有测试覆盖。

## API

### `POST /api/simplify`（旧接口，保持不变）

请求：`{"tolerance": 30, "points": [{"time": 0, "value": 0}, ...]}`

响应仅包含：

```json
{ "indices": [0, 12], "points": [{"time": 0, "value": 0}, {"time": 12, "value": 0}],
  "segment_count": 1 }
```

### `POST /api/simplify-budget`（新接口）

请求：`{"budget": 2, "points": [...]}`（不接受 `tolerance` 等未知字段）

响应（表格、SVG、误差标记共用同一响应）：

```json
{
  "indices": [0, 2, 6],
  "points": [{"time": 0, "value": 0}, {"time": 2, "value": 1}, {"time": 6, "value": 0}],
  "segment_count": 2,
  "budget": 2,
  "max_error": {"numerator": 3, "denominator": 4},
  "segments": [
    {"start": 0, "end": 2, "error": {"numerator": 1, "denominator": 2}, "witness": 1},
    {"start": 2, "end": 6, "error": {"numerator": 3, "denominator": 4}, "witness": 3}
  ]
}
```

`witness` 为该段达到最坏偏差的中间点中最小的原下标；相邻点段没有中间点，为 `null`。
所有分数均为约分有理数（分子非负、分母为正且互质）。非法 budget（0、超过 10、不小于
采样点数、浮点/布尔/字符串）与其它输入问题一律返回 **422**。

## 前端

页面单选切换“阈值模式 / 段数预算模式”：

* 切换模式或编辑输入都会清除与当前数据/模式不匹配的旧结论；
* 预算模式额外展示全程最大偏差（分数文本）、每段见证表（达到全程最坏偏差的段高亮），
  SVG 中以竖虚线画出每个见证点到弦上插值位置的纵向偏差（红色为全程最坏，橙色为段内
  最坏）。

## 目录结构

```
api/                 FastAPI 服务
  app/simplifier.py  整数判定 + 可达图 + 最短路 DP；预算模式（Fraction 代价 + 二分）
  app/schemas.py     严格输入校验（未知字段/浮点/布尔/越界/错误顺序/budget -> 422）
  app/main.py        POST /api/simplify, POST /api/simplify-budget, GET /health
  tests/             pytest：全量子序列枚举（含非整数/并列/零误差对拍）+ HTTP 用例
web/                 React + Vite 单页应用
  src/App.jsx        模式切换、JSON 粘贴、提交、结果与见证表（切换/编辑清除旧结果）
  src/TrajectoryChart.jsx  SVG 原图/约简折线叠加 + 预算模式见证偏差标记
  tests/             Playwright：阈值模式与预算模式各一条端到端流程
docker-compose.yml   web(nginx) + api(uvicorn)
```

## Docker Compose 运行

```bash
docker compose up --build
# web:  http://localhost:8080
# api:  http://localhost:8000  (GET /health)
```

## 本地开发运行

```bash
# 后端（:8000）
cd api
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# 前端（:5173，/api 代理到 :8000）
cd web
npm install
npm run dev
```

## 测试

```bash
# 后端：
#   test_simplifier.py —— 阈值模式小规模全枚举/随机核对最优性
#   test_budget.py     —— 预算模式枚举所有含首尾点的子序列，用整数交叉相乘
#                         （Fraction）对拍，覆盖零误差、并列及非整数最优值
cd api && python -m pytest

# 浏览器端到端（自动拉起 api 与 vite）
cd web && npx playwright install chromium && npx playwright test
```

## 输入示例

```json
{
  "tolerance": 30,
  "points": [
    { "time": 0, "value": 0 },
    { "time": 1, "value": 8 },
    { "time": 2, "value": -5 }
  ]
}
```

```json
{
  "budget": 2,
  "points": [
    { "time": 0, "value": 0 },
    { "time": 1, "value": 0 },
    { "time": 2, "value": 1 }
  ]
}
```

未知字段、非法数值（含小数、布尔、越界）、点数不足/超限、`time` 非严格递增均返回
**422**，页面不会保留上一次的结果。
