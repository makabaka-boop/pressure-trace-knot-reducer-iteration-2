// SVG overlay comparing the original trajectory with the reduced
// polyline.  Both layers (and, whenever witnesses exist, the
// per-segment witness error markers) come from the same API response
// stored by the parent.  The single global witness passed in
// (smallest original index attaining the worst error/multiplier) is the
// exact point highlighted both here (red) and in the table.

const WIDTH = 820;
const HEIGHT = 380;
const MARGIN = { top: 24, right: 24, bottom: 44, left: 64 };

function toPoints(values, xFor, yFor) {
  return values.map((point) => `${xFor(point.time)},${yFor(point.value)}`).join(' ');
}

function niceTicks(min, max, count = 5) {
  // Integer ticks derived without floating point scaling: split the
  // integer span into equal (as possible) integer steps.
  if (min === max) return [min];
  const step = Math.max(1, Math.round((max - min) / count));
  const ticks = [];
  for (let value = min; value <= max; value += step) ticks.push(value);
  if (ticks[ticks.length - 1] !== max) ticks.push(max);
  return ticks;
}

// Exact rational equality for { numerator, denominator } using BigInt
// cross multiplication.
function fractionEqual(a, b) {
  return (
    BigInt(a.numerator) * BigInt(b.denominator)
    === BigInt(b.numerator) * BigInt(a.denominator)
  );
}

// Small glyph marking which side of the interpolated chord the witness
// sits on.  Above points are drawn above the chord, below points under
// it, and collinear witnesses carry no arrow.
const DIRECTION_MARK = {
  above: '▲',
  below: '▼',
  on: '●',
};

export default function TrajectoryChart({
  originalPoints,
  indices,
  simplifiedPoints,
  segments = null,
  maxError = null,
}) {
  const innerWidth = WIDTH - MARGIN.left - MARGIN.right;
  const innerHeight = HEIGHT - MARGIN.top - MARGIN.bottom;

  const times = originalPoints.map((point) => point.time);
  const values = originalPoints.map((point) => point.value);
  const minTime = Math.min(...times);
  const maxTime = Math.max(...times);
  const minValue = Math.min(...values);
  const maxValue = Math.max(...values);

  // Pad the value range so points never sit on the frame edge.
  const valueSpan = Math.max(1, maxValue - minValue);
  const padValue = Math.ceil(valueSpan / 10);
  const yMin = minValue - padValue;
  const yMax = maxValue + padValue;

  const timeSpan = Math.max(1, maxTime - minTime);
  const valueRange = yMax - yMin;

  const xFor = (time) => MARGIN.left + ((time - minTime) / timeSpan) * innerWidth;
  const yFor = (value) =>
    MARGIN.top + innerHeight - ((value - yMin) / valueRange) * innerHeight;

  const xTicks = niceTicks(minTime, maxTime);
  const yTicks = niceTicks(yMin, yMax, 4);

  // For every segment with an intermediate witness, draw a vertical
  // line from the worst original sample to its interpolated position on
  // the retained chord.  Marker geometry mirrors the rational error
  // returned by the API exactly (both endpoints come from the same
  // response).  The red "worst" marker is the unique global witness
  // shared with the table; all other segment witnesses are orange.
  const markers = segments
    ? segments
        .filter((segment) => segment.witnessIndex !== null)
        .map((segment) => {
          const startPoint = originalPoints[segment.start];
          const endPoint = originalPoints[segment.end];
          const witnessPoint = originalPoints[segment.witnessIndex];
          const ratio =
            (witnessPoint.time - startPoint.time) /
            (endPoint.time - startPoint.time);
          const interpolatedValue =
            startPoint.value + (endPoint.value - startPoint.value) * ratio;
          const isWorst =
            maxError !== null &&
            segment.isWorst &&
            fractionEqual(segment.ratioValue, maxError);
          return {
            key: `${segment.start}-${segment.end}`,
            witnessIndex: segment.witnessIndex,
            witnessDirection: segment.witnessDirection,
            isWorst,
            x: xFor(witnessPoint.time),
            yWitness: yFor(witnessPoint.value),
            yInterp: yFor(interpolatedValue),
          };
        })
    : [];

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      role="img"
      aria-label="原始轨迹与约简折线对照图"
    >
      {/* gridlines + y labels */}
      {yTicks.map((tick) => (
        <g key={`y-${tick}`}>
          <line
            className="grid"
            x1={MARGIN.left}
            x2={WIDTH - MARGIN.right}
            y1={yFor(tick)}
            y2={yFor(tick)}
          />
          <text className="axis-label" x={MARGIN.left - 8} y={yFor(tick) + 4} textAnchor="end">
            {tick}
          </text>
        </g>
      ))}

      {/* x labels */}
      {xTicks.map((tick) => (
        <text
          key={`x-${tick}`}
          className="axis-label"
          x={xFor(tick)}
          y={HEIGHT - MARGIN.bottom + 20}
          textAnchor="middle"
        >
          {tick}
        </text>
      ))}

      {/* axes */}
      <line
        className="axis"
        x1={MARGIN.left}
        x2={WIDTH - MARGIN.right}
        y1={HEIGHT - MARGIN.bottom}
        y2={HEIGHT - MARGIN.bottom}
      />
      <line
        className="axis"
        x1={MARGIN.left}
        x2={MARGIN.left}
        y1={MARGIN.top}
        y2={HEIGHT - MARGIN.bottom}
      />

      {/* original trajectory: thin gray with a dot per sample */}
      <polyline
        className="original-line"
        points={toPoints(originalPoints, xFor, yFor)}
      />
      {originalPoints.map((point, index) => (
        <circle
          key={`orig-${index}`}
          className="original-dot"
          cx={xFor(point.time)}
          cy={yFor(point.value)}
          r={3}
        />
      ))}

      {/* reduced polyline: thick blue with highlighted retained points */}
      <polyline
        className="simplified-line"
        points={toPoints(simplifiedPoints, xFor, yFor)}
      />

      {/* witness markers: vertical deviation to the chord */}
      {markers.map((marker) => (
        <g key={`marker-${marker.key}`} className={marker.isWorst ? 'marker-worst' : 'marker-segment'}>
          <line
            className="error-marker"
            x1={marker.x}
            x2={marker.x}
            y1={marker.yWitness}
            y2={marker.yInterp}
          />
          <circle
            className="error-witness"
            cx={marker.x}
            cy={marker.yWitness}
            r={5}
          />
          <circle
            className="error-foot"
            cx={marker.x}
            cy={marker.yInterp}
            r={3}
          />
          <text
            className="error-index"
            x={marker.x}
            y={Math.min(marker.yWitness, marker.yInterp) - 8}
            textAnchor="middle"
          >
            {marker.witnessIndex}
            {marker.witnessDirection
              ? DIRECTION_MARK[marker.witnessDirection] ?? ''
              : ''}
          </text>
        </g>
      ))}

      {simplifiedPoints.map((point, row) => (
        <g key={`kept-${indices[row]}`}>
          <circle
            className="simplified-dot"
            cx={xFor(point.time)}
            cy={yFor(point.value)}
            r={5}
          />
          <text
            className="kept-index"
            x={xFor(point.time)}
            y={yFor(point.value) - 10}
            textAnchor="middle"
          >
            {indices[row]}
          </text>
        </g>
      ))}

      {/* legend */}
      <g className="legend" transform={`translate(${MARGIN.left + 12}, ${MARGIN.top + 8})`}>
        <line className="legend-line legend-original" x1={0} x2={24} y1={0} y2={0} />
        <circle className="legend-dot legend-original" cx={12} cy={0} r={3} />
        <text x={32} y={4}>原始轨迹（{originalPoints.length} 点）</text>
        <line className="legend-line legend-simplified" x1={210} x2={234} y1={0} y2={0} />
        <circle className="legend-dot legend-simplified" cx={222} cy={0} r={5} />
        <text x={242} y={4}>约简折线（{simplifiedPoints.length} 点）</text>
        {markers.length > 0 && (
          <g transform="translate(420, 0)">
            <line className="legend-line legend-error" x1={0} x2={24} y1={0} y2={0} />
            <circle className="legend-dot legend-error" cx={12} cy={0} r={4} />
            <text x={32} y={4}>见证点纵向偏差（▲线上方 ▼线下方；红=全程最坏）</text>
          </g>
        )}
      </g>
    </svg>
  );
}
