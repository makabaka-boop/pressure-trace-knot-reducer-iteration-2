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
* **方向性误差配置（可选，两种模式共用）**：请求可带
  `directed_error: {"above": A, "below": B}`（均为正整数），分别限制原始点位于插值线
  **上方**与**下方**的纵向偏差；点恰在线上不消耗任何界限。
  * 阈值模式：用两个界限裁决每条候选线段——上方点偏差 ≤ A、下方点偏差 ≤ B（边界相等
    合法），随后仍是最少段数、下标字典序。
  * 预算模式：最小化使所有偏差分别落入 `倍率·A`、`倍率·B` 的**公共倍率**（精确约分
    有理数，可能是非整数），再按最少段数、下标字典序裁决。
  * 阈值请求**不得**同时给 `tolerance` 与 `directed_error`（422）；未启用配置时旧接口
    的响应字段与排序逐项不变。两个模式返回达到最坏倍率的**原始点下标及偏差方向**
    （above/below/on），页面表格高亮行与 SVG 红色标记指向同一见证。

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

方向性配置下，带符号的叉积

```
s = (v_k - v_i) * (t_j - t_i) - (v_j - v_i) * (t_k - t_i)
```

决定点的方向：`s > 0` 在插值线上方、`s < 0` 在下方、`s = 0` 在线上。候选线段 `i -> j`
的代价是段内最大的**侧别比值** `|s| / (t_j - t_i) / 界限`（上方除以 A、下方除以 B），
全程仍是 `Fraction` 精确比较：阈值模式要求比值 ≤ 1；预算模式对去重排序后的候选比值二分
求最小可行公共倍率。方向性模式与旧模式共用同一份候选线段代价矩阵、可达路径 DP（
`_reachable_from_costs` / `_minimum_segments`）与字典序重建（
`_lexicographically_smallest_path`）。

## 求解思路（预算模式）

1. 预算计算每一条可能的段 `i -> j` 的代价（段内最大偏差，`Fraction`）与见证下标
   （并列时取最小下标）。
2. 最优全程偏差必等于某条段的代价：把所有段代价去重排序后二分，可行性判定是“DAG 上
   是否存在边数 ≤ budget、每边代价 ≤ 候选值的 0→n-1 路径”（逆序 DP）。
3. 找到最优偏差后，在对应可达图上再做一次逆序最短路 DP（同偏差下最少段），正向重建时
   在所有仍在最短路上的后继里取最小下标，得到字典序最小解。
4. 零误差（共线）、并列最优、分母不为 1 的非整数最优值均有测试覆盖。

## API

### `POST /api/simplify`（旧接口，无配置时保持不变）

请求：`{"tolerance": 30, "points": [{"time": 0, "value": 0}, ...]}`

响应仅包含：

```json
{ "indices": [0, 12], "points": [{"time": 0, "value": 0}, {"time": 12, "value": 0}],
  "segment_count": 1 }
```

启用方向性配置时（不得再给 `tolerance`）：

请求：`{"directed_error": {"above": 30, "below": 12}, "points": [...]}`

```json
{
  "indices": [0, 6, 12],
  "points": [ ... ],
  "segment_count": 2,
  "directed_error": {"above": 30, "below": 12},
  "worst_ratio": {"numerator": 3, "denominator": 4},
  "witness": {"index": 8, "direction": "below"},
  "segments": [
    {"start": 0, "end": 6, "ratio": {"numerator": 0, "denominator": 1}, "witness": null},
    {"start": 6, "end": 12, "ratio": {"numerator": 3, "denominator": 4},
     "witness": {"index": 8, "direction": "below"}}
  ]
}
```

阈值裁决通过时 `worst_ratio` 必 ≤ 1（全共线时为 0，`witness` 为线上点且方向 `"on"`；
无中间点的全相邻段解为 `null`）。

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

附带可选的方向性配置时，响应改为 `worst_ratio`（最小公共倍率）+ 带方向的
`witness: {index, direction}`（每段同形），并回显 `directed_error`；表格高亮行与
SVG 红色标记均指向该全局见证点。例如
`{"budget": 2, "directed_error": {"above": 1, "below": 2}, "points": [...]}`：

```json
{
  "indices": [0, 2, 6],
  "points": [ ... ],
  "segment_count": 2,
  "budget": 2,
  "directed_error": {"above": 1, "below": 2},
  "worst_ratio": {"numerator": 3, "denominator": 10},
  "witness": {"index": 4, "direction": "below"},
  "segments": [
    {"start": 0, "end": 2, "ratio": {"numerator": 1, "denominator": 10},
     "witness": {"index": 1, "direction": "below"}},
    {"start": 2, "end": 6, "ratio": {"numerator": 3, "denominator": 10},
     "witness": {"index": 4, "direction": "below"}}
  ]
}
```

`directed_error` 的两个界限必须是 `[1, 10^6]` 的真整数（浮点/布尔/字符串/0/负数/越界/
缺字段/多余字段均 422）。

## 前端

页面单选切换“阈值模式 / 段数预算模式”：

* 切换模式或编辑输入都会清除与当前数据/模式不匹配的旧结论；
* 预算模式额外展示全程最大偏差（分数文本）、每段见证表（达到全程最坏偏差的段高亮），
  SVG 中以竖虚线画出每个见证点到弦上插值位置的纵向偏差（红色为全程最坏，橙色为段内
  最坏）；
* 启用 `directed_error` 时两种模式都展示见证表，多出“偏差方向”列（插值线上方 ▲ /
  下方 ▼ / 恰在线上 ●）；预算模式标题改为最小公共倍率。页面顶部的见证说明、表格唯一
  高亮行与 SVG 唯一红色标记使用响应中的同一个全局见证。

## 目录结构

```
api/                 FastAPI 服务
  app/simplifier.py  整数判定 + 可达图 + 最短路 DP；预算模式（Fraction 代价 + 二分）；
                     方向性模式（侧别比值代价，复用同一套候选段/可达/重建）
  app/schemas.py     严格输入校验（未知字段/浮点/布尔/越界/错误顺序/budget/directed_error
                     /tolerance 与配置同发 -> 422）
  app/main.py        POST /api/simplify, POST /api/simplify-budget, GET /health
  tests/             pytest：全量子序列枚举（含非整数倍率/上下偏差平局/边界相等对拍）+ HTTP 用例
web/                 React + Vite 单页应用
  src/App.jsx        模式切换、JSON 粘贴、提交、结果与见证表（切换/编辑清除旧结果）
  src/TrajectoryChart.jsx  SVG 原图/约简折线叠加 + 见证偏差方向标记
  verify-dom.mjs     无浏览器环境的 jsdom DOM 验证（需本机 api:8000；npm run test:dom）
  tests/             Playwright：阈值/预算/方向性模式端到端流程
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
#   test_simplifier.py    —— 阈值模式小规模全枚举/随机核对最优性
#   test_budget.py        —— 预算模式枚举所有含首尾点的子序列，用整数交叉相乘
#                            （Fraction）对拍，覆盖零误差、并列及非整数最优值
#   test_directional.py   —— 方向性两模式枚举所有保留点子序列对拍，覆盖非整数
#                            公共倍率、上/下偏差并列（最小下标 + 方向）与边界相等
#   test_directional_api.py / test_*_api.py —— HTTP 契约、422、旧接口逐项不变
cd api && python -m pytest

# 浏览器端到端（自动拉起 api 与 vite）
cd web && npx playwright install chromium && npx playwright test

# 无浏览器环境的 DOM 级验证（需要 api 已在 :8000）
(cd api && python -m uvicorn app.main:app --port 8000 &)
cd web && npm run test:dom
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

方向性配置（两模式通用；阈值模式下不要带 `tolerance`）：

```json
{
  "budget": 2,
  "directed_error": { "above": 1, "below": 2 },
  "points": [
    { "time": 0, "value": 0 },
    { "time": 1, "value": 0 },
    { "time": 2, "value": 1 },
    { "time": 3, "value": 0 },
    { "time": 4, "value": -1 }
  ]
}
```

未知字段、非法数值（含小数、布尔、越界）、点数不足/超限、`time` 非严格递增、
阈值请求同时给出 `tolerance` 与 `directed_error`（或两者皆无）、方向性界限不是
`[1, 10^6]` 真整数，均返回 **422**，页面不会保留上一次的结果。
