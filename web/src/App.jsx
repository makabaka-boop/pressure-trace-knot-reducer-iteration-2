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

const EXAMPLES = new Set([TOLERANCE_EXAMPLE.trim(), BUDGET_EXAMPLE.trim()]);

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
    if (rawInput.trim() === '' || EXAMPLES.has(rawInput.trim())) {
      setRawInput(next === 'tolerance' ? TOLERANCE_EXAMPLE : BUDGET_EXAMPLE);
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
      setError('输入不是合法 JSON，请检查后重试。');
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

  return (
    <main className="page">
      <header>
        <h1>风洞压力轨迹约简</h1>
        <p className="subtitle">
          阈值模式：在纵向误差不超过 tolerance 的前提下求保留点最少的折线；
          预算模式：给定至多 K 段，求最小的真实最大纵向偏差（约分有理数），
          同偏差取最少段、再取下标序列字典序最小者。所有偏差均用整数交叉相乘精确比较。
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
          阈值模式（tolerance）
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
            ? '整数字段 tolerance'
            : '整数字段 budget（段数上限）'}
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
          {isBudget ? (
            <p className="summary">
              原始 {request.points.length} 个采样点 → 保留{' '}
              {result.indices.length} 个点、{result.segment_count} 条线段
              （预算 {result.budget} 段）；全程最大纵向偏差 ={' '}
              <strong data-testid="max-error">
                {formatFraction(result.max_error)}
              </strong>
              （约分有理数，整数交叉相乘）
            </p>
          ) : (
            <p className="summary">
              原始 {request.points.length} 个采样点 → 保留{' '}
              {result.indices.length} 个点、{result.segment_count} 条线段；
              tolerance = {request.tolerance}
            </p>
          )}

          <TrajectoryChart
            originalPoints={request.points}
            indices={result.indices}
            simplifiedPoints={result.points}
            segments={isBudget ? result.segments : null}
            maxError={isBudget ? result.max_error : null}
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

          {isBudget && (
            <>
              <h3>每段最坏偏差与见证点（可按原下标复核）</h3>
              <table data-testid="segment-table">
                <thead>
                  <tr>
                    <th>段</th>
                    <th>起点下标</th>
                    <th>终点下标</th>
                    <th>段内最坏偏差</th>
                    <th>见证原下标</th>
                  </tr>
                </thead>
                <tbody>
                  {result.segments.map((segment, order) => (
                    <tr
                      key={`${segment.start}-${segment.end}`}
                      className={
                        fractionEqual(segment.error, result.max_error)
                          ? 'worst-row'
                          : ''
                      }
                    >
                      <td>{order + 1}</td>
                      <td>{segment.start}</td>
                      <td>{segment.end}</td>
                      <td>{formatFraction(segment.error)}</td>
                      <td>
                        {segment.witness === null
                          ? '—（相邻点）'
                          : segment.witness}
                      </td>
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
