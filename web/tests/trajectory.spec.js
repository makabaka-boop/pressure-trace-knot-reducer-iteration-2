import { expect, test } from '@playwright/test';

// Sawtooth with amplitude 5; tolerance 5 puts every intermediate
// sample exactly on the error boundary of the flat end-to-end segment
// (the boundary is inclusive), so the optimal (and lexicographically
// smallest) solution keeps exactly the endpoints.
const TOLERANCE_REQUEST = {
  tolerance: 5,
  points: [
    { time: 0, value: 0 },
    { time: 1, value: 5 },
    { time: 2, value: 0 },
    { time: 3, value: 5 },
    { time: 4, value: 0 },
    { time: 5, value: 5 },
    { time: 6, value: 0 },
  ],
};

// Budget mode: the end-to-end chord has worst deviation 1, while the
// optimal two-segment split 0 -> 2 -> 6 has bottleneck 3/4.  The error
// is a non-integer rational and must never come from a rounded integer
// tolerance.  Segments 0->2 and 2->6 each keep one worst witness.
const BUDGET_REQUEST = {
  budget: 2,
  points: [
    { time: 0, value: 0 },
    { time: 1, value: 0 },
    { time: 2, value: 1 },
    { time: 3, value: 0 },
    { time: 4, value: 1 },
    { time: 5, value: 0 },
    { time: 6, value: 0 },
  ],
};

test('tolerance mode: paste JSON, solve once, draw both trajectories', async ({
  page,
}) => {
  await page.goto('/');

  // One input action: paste the JSON payload into the textarea.
  await page.locator('#json-input').fill(JSON.stringify(TOLERANCE_REQUEST));
  await page.getByRole('button', { name: '提交计算' }).click();

  // Result panel renders with the single shared response.
  const panel = page.getByTestId('result-panel');
  await expect(panel.locator('.summary')).toContainText('原始 7 个采样点');
  await expect(panel.locator('.summary')).toContainText('保留 2 个点、1 条线段');

  // Table (driven by the response) lists the two endpoints.
  const rows = panel.locator('table tbody tr');
  await expect(rows).toHaveCount(2);
  await expect(rows.first().locator('td')).toHaveText(['0', '0', '0']);
  await expect(rows.last().locator('td')).toHaveText(['6', '6', '0']);

  // SVG: one original dot per sample, two highlighted retained points,
  // and both polylines are drawn with non-trivial geometry.
  const svg = panel.locator('svg.chart');
  await expect(svg.locator('circle.original-dot')).toHaveCount(7);
  await expect(svg.locator('circle.simplified-dot')).toHaveCount(2);

  const simplifiedLine = svg.locator('polyline.simplified-line');
  const simplifiedPoints = (await simplifiedLine.getAttribute('points'))
    .trim()
    .split(/\s+/);
  expect(simplifiedPoints).toHaveLength(2);

  // Tolerance mode never renders budget-only artifacts.
  await expect(panel.getByTestId('segment-table')).toHaveCount(0);
  await expect(svg.locator('.error-marker')).toHaveCount(0);

  await expect(page.locator('.error')).toHaveCount(0);
});

test('budget mode: exact rational error, witness table and SVG markers', async ({
  page,
}) => {
  await page.goto('/');

  await page.getByText('段数预算模式（budget').click();
  await page.locator('#json-input').fill(JSON.stringify(BUDGET_REQUEST));
  await page.getByRole('button', { name: '提交计算' }).click();

  const panel = page.getByTestId('result-panel');
  await expect(panel).toBeVisible();
  await expect(panel.locator('.summary')).toContainText('原始 7 个采样点');
  await expect(panel.locator('.summary')).toContainText('预算 2 段');
  // Exact non-integer optimum (3/4), not a rounded integer.
  await expect(panel.getByTestId('max-error')).toHaveText('3/4');

  // Retained points come from the same shared response.
  const keptRows = panel.locator('table').first().locator('tbody tr');
  await expect(keptRows).toHaveCount(3);
  await expect(keptRows.first().locator('td')).toHaveText(['0', '0', '0']);
  await expect(keptRows.nth(1).locator('td')).toHaveText(['2', '2', '1']);
  await expect(keptRows.last().locator('td')).toHaveText(['6', '6', '0']);

  // Per-segment witness table: segment 2 -> 6 carries the global worst
  // error 3/4 with the smallest attaining original index (3).
  const segmentRows = panel.getByTestId('segment-table').locator('tbody tr');
  await expect(segmentRows).toHaveCount(2);
  await expect(segmentRows.first().locator('td')).toHaveText([
    '1', '0', '2', '1/2', '1',
  ]);
  await expect(segmentRows.last().locator('td')).toHaveText([
    '2', '2', '6', '3/4', '3',
  ]);
  await expect(segmentRows.last()).toHaveClass(/worst-row/);

  // SVG witness markers: one per segment with an intermediate witness.
  const svg = panel.locator('svg.chart');
  const worstMarkers = svg.locator('g.marker-worst');
  const normalMarkers = svg.locator('g.marker-segment');
  await expect(worstMarkers).toHaveCount(1);
  await expect(normalMarkers).toHaveCount(1);
  await expect(worstMarkers.locator('.error-witness')).toHaveCount(1);
  await expect(worstMarkers.locator('.error-index')).toHaveText('3');
  await expect(normalMarkers.locator('.error-index')).toHaveText('1');

  // One marker line per segment, plus the foot on the interpolated chord.
  await expect(svg.locator('.error-marker')).toHaveCount(2);
  await expect(svg.locator('.error-foot')).toHaveCount(2);

  await expect(page.locator('.error')).toHaveCount(0);

  // Switching modes discards the mismatched budget conclusion.
  await page.getByText('阈值模式（tolerance）').click();
  await expect(panel).toHaveCount(0);
  await expect(page.locator('textarea')).toHaveValue(/.+/);
});

test('budget mode: editing the JSON clears the stale conclusion', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByText('段数预算模式（budget').click();
  await page.locator('#json-input').fill(JSON.stringify(BUDGET_REQUEST));
  await page.getByRole('button', { name: '提交计算' }).click();
  const panel = page.getByTestId('result-panel');
  await expect(panel).toBeVisible();

  // Any edit to the payload invalidates the conclusion shown for it.
  await page.locator('#json-input').press('End');
  await page.locator('#json-input').press('1');
  await expect(panel).toHaveCount(0);
});

test('budget equal to point count is rejected with 422', async ({ page }) => {
  await page.goto('/');
  await page.getByText('段数预算模式（budget').click();
  const bad = { budget: 7, points: BUDGET_REQUEST.points };
  await page.locator('#json-input').fill(JSON.stringify(bad));
  await page.getByRole('button', { name: '提交计算' }).click();
  await expect(page.locator('.error')).toContainText('422');
  await expect(page.getByTestId('result-panel')).toHaveCount(0);
});
