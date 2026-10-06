import { useState } from 'react';
import TrajectoryChart from './TrajectoryChart.jsx';

const TOLERANCE_EXAMPLE = `{
  "tolerance": 30,
  "points": [
    { "time": 0, "value": 0 },
    { "time": 1, "value": 8 },
    { "time": 2, "value": -5 },
    { "time": 3, "value": 12 },
    { "time": 4, "value": 40 },
    { "time": 5, "value": 55 },
    { "time": 6, "value": 48 },
    { "time": 7, "value": 60 },
    { "time": 8, "value": 20 },
    { "time": 9, "value": 10 },
    { "time": 10, "value": -8 },
    { "time": 11, "value": 2 },
    { "time": 12, "value": 0 }
  ]
}`;

const BUDGET_EXAMPLE = `{
  "budget": 2,
  "points": [
    { "time": 0, "value": 0 },
    { "time": 1, "value": 0 },
    { "time": 2, "value": 1 },
    { "time": 3, "value": 0 },
    { "time": 4, "value": 1 },
    { "time": 5, "value": 0 },
    { "time": 6, "value": 0 }
  ]
}`;

// Directional error configuration: above/below share a positive integer
// bound (the threshold mode adjudicates at multiplier 1; the budget
// mode minimises a common rational multiplier).
const DIRECTED_TOLERANCE_EXAMPLE = `{
  "directed_error": { "above": 30, "below": 12 },
  "points": [
    { "time": 0, "value": 0 },
    { "time": 1, "value": 8 },
    { "time": 2, "value": -5 },
    { "time": 3, "value": 12 },
    { "time": 4, "value": 40 },
    { "time": 5, "value": 55 },
    { "time": 6, "value": 48 },
    { "time": 7, "value": 60 },
    { "time": 8, "value": 20 },
    { "time": 9, "value": 10 },
    { "time": 10, "value": -8 },
    { "time": 11, "value": 2 },
    { "time": 12, "value": 0 }
  ]
}`;

const DIRECTED_BUDGET_EXAMPLE = `{
  "budget": 2,
  "directed_error": { "above": 1, "below": 2 },
  "points": [
    { "time": 0, "value": 0 },
    { "time": 1, "value": 0 },
    { "time": 2, "value": 1 },
    { "time": 3, "value": 0 },
    { "time": 4, "value": -1 },
    { "time": 5, "value": 0 },
    { "time": 6, "value": 0 }
  ]
}`;

const EXAMPLES = new Set([
  TOLERANCE_EXAMPLE.trim(),
  BUDGET_EXAMPLE.trim(),
  DIRECTED_TOLERANCE_EXAMPLE.trim(),
  DIRECTED_BUDGET_EXAMPLE.trim(),
]);

function formatApiErrors(detail) {
  if (!Array.isArray(detail)) return String(detail);
  return detail
    .map((error) => {
      const loc = Array.isArray(error.loc)
        ? error.loc.filter((part) => part !== 'body').join('.')
        : '';
      return loc ? `${loc}: ${error.msg}` : error.msg;
    })
    .join('\n');
}

// Exact reduced rational: { numerator, denominator }.
function formatFraction(value) {
  return value.denominator === 1
    ? String(value.numerator)
    : `${value.numerator}/${value.denominator}`;
}

// Compare two reduced rationals by integer cross multiplication using
// BigInt so products beyond the JS safe-integer range stay exact.
function fractionEqual(a, b) {
  return (
    BigInt(a.numerator) * BigInt(b.denominator)
    === BigInt(b.numerator) * BigInt(a.denominator)
  );
}

const DIRECTION_TEXT = {
  above: '插值线上方',
  below: '插值线下方',
  on: '恰在线上',
};

function formatDirection(direction) {
  return DIRECTION_TEXT[direction] ?? direction;
}

// Normalise either witness shape (legacy integer or {index, direction}).
function witnessIndex(witness) {
  if (witness === null || witness === undefined) return null;
  return typeof witness === 'number' ? witness : witness.index;
}

function witnessDirection(witness) {
  if (witness === null || typeof witness === 'number') return null;
  return witness.direction ?? null;
}

export default function App() {
  const [mode, setMode] = useState('tolerance'); // 'tolerance' | 'budget'
  const [rawInput, setRawInput] = useState(TOLERANCE_EXAMPLE);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const request = result?.request ?? null;

  function handleModeChange(next) {
    if (next === mode) return;
    setMode(next);
    // A result computed under the other mode never stays on screen.
    setResult(null);
    setError('');
    // Only swap the built-in sample; keep whatever the user typed.
    // When on a built-in example, preserve its flavour (plain vs.
    // directional) across the mode switch.
    const trimmed = rawInput.trim();
    if (trimmed === '' || EXAMPLES.has(trimmed)) {
      const directed = trimmed.includes('directed_error');
      if (directed) {
        setRawInput(
          next === 'tolerance'
            ? DIRECTED_TOLERANCE_EXAMPLE
            : DIRECTED_BUDGET_EXAMPLE,
        );
      } else {
        setRawInput(
          next === 'tolerance' ? TOLERANCE_EXAMPLE : BUDGET_EXAMPLE,
        );
      }
    }
  }

  function handleInputChange(event) {
    setRawInput(event.target.value);
    // Editing the data invalidates any conclusion shown for it.
    setResult(null);
    setError('');
  }

  async function handleSubmit(event) {
    event.preventDefault();
    // A fresh submission always discards the previous outcome: on a
    // validation failure the page must never keep stale results.
    setResult(null);
    setError('');

    let parsed;
    try {
      parsed = JSON.parse(rawInput);
    } catch {
      setError('输入不是合法 JSON，请检查后再试。');
      return;
    }

    const endpoint =
      mode === 'tolerance' ? '/api/simplify' : '/api/simplify-budget';

    setLoading(true);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(parsed),
      });

      if (response.status === 422) {
        const payload = await response.json().catch(() => null);
        setError(
          payload
            ? `输入校验失败（422）：\n${formatApiErrors(payload.detail)}`
            : '输入校验失败（422）。',
        );
        return;
      }
      if (!response.ok) {
        setError(`求解失败，服务端返回 ${response.status}。`);
        return;
      }

      const data = await response.json();
      // Table, SVG and error markers all render from this one response.
      setResult({ mode, request: parsed, ...data });
    } catch (err) {
      setError(`无法连接求解服务：${err.message}`);
    } finally {
      setLoading(false);
    }
  }

  const isBudget = result?.mode === 'budget';
  // A response carries segments whenever witnesses exist: always in
  // budget mode, and in threshold mode only with the directional config.
  const hasSegments = Array.isArray(result?.segments);
  const isDirected = result?.directed_error != null;
  // The single witness shared by the table and the SVG.  In legacy
  // budget mode the global witness is the segment whose error equals
  // max_error (its per-segment witness is an integer index); in the
  // directional modes the response provides it explicitly.
  let globalWitnessIndex = null;
  let globalWitnessDirection = null;
  let globalWorstValue = null;
  if (result) {
    if (isDirected) {
      globalWitnessIndex = witnessIndex(result.witness);
      globalWitnessDirection = witnessDirection(result.witness);
      globalWorstValue = result.worst_ratio;
    } else if (hasSegments) {
      const worstSegment = result.segments.find((segment) =>
        fractionEqual(segment.error, result.max_error),
      );
      globalWitnessIndex = worstSegment
        ? witnessIndex(worstSegment.witness)
        : null;
      globalWorstValue = result.max_error;
    }
  }

  // Normalise per-segment rows so the table/chart code is shared.  A
  // segment is "the worst" when its witness is the single global
  // witness; this predicate is used identically by the table highlight
  // and the red SVG marker, so both always point at the same original
  // point.  In legacy budget mode (integer witness, no direction) every
  // segment tied at max_error is highlighted as before.
  const isGlobalWorstSegment = (row) => {
    if (row.witnessIndex === null) return false;
    if (isDirected) {
      return row.witnessIndex === globalWitnessIndex;
    }
    return (
      globalWorstValue != null && fractionEqual(row.ratioValue, globalWorstValue)
    );
  };

  const segmentRows = hasSegments
    ? result.segments.map((segment) => {
        const ratioValue = isDirected ? segment.ratio : segment.error;
        return {
          start: segment.start,
          end: segment.end,
          ratioValue,
          witness: segment.witness,
          witnessIndex: witnessIndex(segment.witness),
          witnessDirection: witnessDirection(segment.witness),
        };
      })
    : [];
  segmentRows.forEach((row) => {
    row.isWorst = isGlobalWorstSegment(row);
  });

  const directedConfig = result?.directed_error ?? null;

  return (
    <main className="page">
      <header>
        <h1>风洞压力轨迹约简</h1>
        <p className="subtitle">
          阈值模式：在纵向误差不超过 tolerance 的前提下求保留点最少的折线；
          预算模式：给定至多 K 段，求最小的真实最大纵向偏差（约分有理数），
          同偏差取最少段、再取下标序列字典序最小者。两种模式均可选
          <em> directed_error </em>
          方向性配置（正整数 above / below，分别限制插值线上方与下方的偏差）：
          阈值模式按两条界限裁决候选线段，预算模式最小化使两侧偏差同时入界的公共倍率。
          所有倍率与比较均为精确有理数整数交叉相乘。
        </p>
      </header>

      <fieldset className="mode-switch">
        <legend>求解模式</legend>
        <label>
          <input
            type="radio"
            name="mode"
            checked={mode === 'tolerance'}
            onChange={() => handleModeChange('tolerance')}
          />
          阈值模式（tolerance 或 directed_error）
        </label>
        <label>
          <input
            type="radio"
            name="mode"
            checked={mode === 'budget'}
            onChange={() => handleModeChange('budget')}
          />
          段数预算模式（budget，1–10 且小于采样点数）
        </label>
      </fieldset>

      <form className="input-panel" onSubmit={handleSubmit}>
        <label htmlFor="json-input">
          轨迹 JSON（2–120 个点，time 为 0–10<sup>9</sup> 严格递增整数；
          {mode === 'tolerance'
            ? '整数字段 tolerance，或方向性配置 directed_error（正整数 above/below，二者不可同时给出）'
            : '整数字段 budget（段数上限），可选 directed_error（正整数 above/below）'}
          ）
        </label>
        <textarea
          id="json-input"
          spellCheck="false"
          rows={18}
          value={rawInput}
          onChange={handleInputChange}
        />
        <div className="actions">
          <button type="submit" disabled={loading}>
            {loading ? '求解中…' : '提交计算'}
          </button>
        </div>
        {error && (
          <pre className="error" role="alert">
            {error}
          </pre>
        )}
      </form>

      {result && (
        <section className="result-panel" data-testid="result-panel">
          <h2>结果</h2>
          {isBudget && isDirected ? (
            <p className="summary">
              原始 {request.points.length} 个采样点 → 保留{' '}
              {result.indices.length} 个点、{result.segment_count} 条线段
              （预算 {result.budget} 段；方向界限 上 {directedConfig.above} /
              下 {directedConfig.below}）；最小公共倍率 ={' '}
              <strong data-testid="max-error">
                {formatFraction(result.worst_ratio)}
              </strong>
              （约分有理数，整数交叉相乘）
            </p>
          ) : isBudget ? (
            <p className="summary">
              原始 {request.points.length} 个采样点 → 保留{' '}
              {result.indices.length} 个点、{result.segment_count} 条线段
              （预算 {result.budget} 段）；全程最大纵向偏差 ={' '}
              <strong data-testid="max-error">
                {formatFraction(result.max_error)}
              </strong>
              （约分有理数，整数交叉相乘）
            </p>
          ) : isDirected ? (
            <p className="summary">
              原始 {request.points.length} 个采样点 → 保留{' '}
              {result.indices.length} 个点、{result.segment_count} 条线段；
              方向性界限 上 {directedConfig.above} / 下{' '}
              {directedConfig.below}，裁决倍率 ={' '}
              <strong data-testid="max-error">
                {formatFraction(result.worst_ratio)}
              </strong>
            </p>
          ) : (
            <p className="summary">
              原始 {request.points.length} 个采样点 → 保留{' '}
              {result.indices.length} 个点、{result.segment_count} 条线段；
              tolerance = {request.tolerance}
            </p>
          )}

          {isDirected && globalWitnessIndex !== null && (
            <p className="summary" data-testid="global-witness">
              达到最坏倍率的原始点：下标 <strong>{globalWitnessIndex}</strong>
              （{formatDirection(globalWitnessDirection)}），
              表格高亮行与 SVG 红色标记指向同一见证点。
            </p>
          )}

          <TrajectoryChart
            originalPoints={request.points}
            indices={result.indices}
            simplifiedPoints={result.points}
            segments={hasSegments ? segmentRows : null}
            maxError={globalWorstValue}
          />

          <h3>保留下标与对应采样点（与上图来自同一响应）</h3>
          <table>
            <thead>
              <tr>
                <th>原下标</th>
                <th>time</th>
                <th>value</th>
              </tr>
            </thead>
            <tbody>
              {result.indices.map((index, row) => (
                <tr key={index}>
                  <td>{index}</td>
                  <td>{result.points[row].time}</td>
                  <td>{result.points[row].value}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {hasSegments && (
            <>
              <h3>
                {isDirected
                  ? '每段最坏倍率与见证点（含偏差方向，可按原下标复核）'
                  : '每段最坏偏差与见证点（可按原下标复核）'}
              </h3>
              <table data-testid="segment-table">
                <thead>
                  <tr>
                    <th>段</th>
                    <th>起点下标</th>
                    <th>终点下标</th>
                    <th>{isDirected ? '段内最坏倍率' : '段内最坏偏差'}</th>
                    <th>见证原下标</th>
                    {isDirected && <th>偏差方向</th>}
                  </tr>
                </thead>
                <tbody>
                  {segmentRows.map((segment, order) => (
                    <tr
                      key={`${segment.start}-${segment.end}`}
                      className={segment.isWorst ? 'worst-row' : ''}
                      data-testid="segment-row"
                    >
                      <td>{order + 1}</td>
                      <td>{segment.start}</td>
                      <td>{segment.end}</td>
                      <td>{formatFraction(segment.ratioValue)}</td>
                      <td>
                        {segment.witnessIndex === null
                          ? '—（相邻点）'
                          : segment.witnessIndex}
                      </td>
                      {isDirected && (
                        <td>
                          {segment.witnessDirection === null
                            ? '—'
                            : formatDirection(segment.witnessDirection)}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </section>
      )}
    </main>
  );
}
