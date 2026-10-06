"""Optimal polyline simplification under integer/rational error bounds.

Two solvers share the same DAG (visibility graph) machinery:

* :func:`simplify` -- the legacy integer-tolerance mode.  Given an
  integer ``tolerance`` it returns the shortest retained-index
  subsequence (fewest segments) for which every intermediate sample
  lies within ``tolerance`` of its segment, breaking ties by the
  lexicographically smallest index sequence.

* :func:`simplify_with_budget` -- the segment-budget mode.  Given an
  upper bound ``budget`` on the number of segments it minimises the
  *true* worst vertical interpolation error over all segments, returns
  it as a reduced rational, then breaks ties by (1) using as few
  segments as possible and (2) choosing the lexicographically smallest
  retained-index sequence.  Every segment also carries the smallest
  original index attaining that segment's worst deviation (a
  re-checkable witness).

Both modes additionally accept an optional *directional* configuration
(two positive integer bounds, one for samples above the interpolated
chord and one for samples below it):

* :func:`simplify_directional` -- adjudicates every candidate segment
  with the two bounds (a point consumes ``deviation / bound`` of its
  own side); the shortest-path/lexicographic tie-breaks are unchanged.

* :func:`simplify_with_budget_directional` -- minimises the *common*
  multiplier of the two bounds for which every deviation fits, again
  followed by fewest segments and lexicographic order.

The directional modes build the same candidate-segment cost matrices
and feed them into the same reachability/shortest-path/lexicographic
machinery as the legacy modes; only the per-edge cost changes (a
side-aware rational ratio instead of an absolute deviation).

Every comparison is performed with integer cross multiplication
(:class:`fractions.Fraction` reduces the result exactly); no floating
point arithmetic is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

# Direction of a sample relative to its interpolated chord.
ABOVE = "above"  # sample lies strictly above the interpolation line
BELOW = "below"  # sample lies strictly below the interpolation line
ON_LINE = "on"  # sample lies exactly on the interpolation line


# ---------------------------------------------------------------------------
# Tolerance mode (legacy, integer cross multiplication)
# ---------------------------------------------------------------------------


def within_segment(
    t_i: int,
    v_i: int,
    t_j: int,
    v_j: int,
    t_k: int,
    v_k: int,
    tolerance: int,
) -> bool:
    """Return whether sample *k* is within ``tolerance`` of segment i-j.

    The interpolated value at ``t_k`` is

        v_i + (v_j - v_i) * (t_k - t_i) / (t_j - t_i)

    so the condition ``|v_k - interp| <= tolerance`` is cross-multiplied
    by the positive denominator ``(t_j - t_i)``::

        |(v_k - v_i) * (t_j - t_i) - (v_j - v_i) * (t_k - t_i)|
            <= tolerance * (t_j - t_i)

    Every factor is an integer, hence the result is exact.
    """
    dt = t_j - t_i
    deviation = (v_k - v_i) * dt - (v_j - v_i) * (t_k - t_i)
    if deviation < 0:
        deviation = -deviation
    return deviation <= tolerance * dt


def _reachable(times: list[int], values: list[int], tolerance: int) -> list[int]:
    """Build the visibility graph as bit masks.

    Bit ``j`` of ``reachable[i]`` is set when every sample strictly
    between ``i`` and ``j`` is within ``tolerance`` of the straight
    segment connecting them.  A failing intermediate point does *not*
    permit an early break: a later point can come back inside the error
    corridor even when an earlier one lies outside it.
    """
    n = len(times)
    reachable = [0] * n
    for i in range(n - 1):
        mask = 0
        for j in range(i + 1, n):
            ok = True
            for k in range(i + 1, j):
                if not within_segment(
                    times[i], values[i],
                    times[j], values[j],
                    times[k], values[k],
                    tolerance,
                ):
                    ok = False
                    break
            if ok:
                mask |= 1 << j
        reachable[i] = mask
    return reachable


def _minimum_segments(reachable: list[int], n: int) -> list[int]:
    """Minimum segment count from every node to node ``n - 1``.

    The visibility graph is a DAG (all edges go forward in index), so a
    reverse sweep is exact.
    """
    infinity = n + 1
    dist = [infinity] * n
    dist[n - 1] = 0
    for i in range(n - 2, -1, -1):
        mask = reachable[i]
        best = infinity
        while mask:
            bit = mask & -mask
            j = bit.bit_length() - 1
            candidate = dist[j] + 1
            if candidate < best:
                best = candidate
            mask ^= bit
        dist[i] = best
    return dist


def _lexicographically_smallest_path(
    reachable: list[int],
    dist: list[int],
    n: int,
) -> list[int]:
    """Reconstruct the lexicographically smallest shortest path.

    Walking forward and always taking the *smallest* reachable next
    index that still lies on a shortest path yields the lexicographically
    smallest optimum.
    """
    path = [0]
    while path[-1] != n - 1:
        i = path[-1]
        mask = reachable[i]
        chosen = None
        while mask:
            bit = mask & -mask
            j = bit.bit_length() - 1
            if dist[j] == dist[i] - 1:
                chosen = j  # bits are inspected in ascending j
                break
            mask ^= bit
        if chosen is None:  # pragma: no cover - adjacent nodes always connect
            raise RuntimeError("internal error: path reconstruction failed")
        path.append(chosen)
    return path


def simplify(
    times: list[int],
    values: list[int],
    tolerance: int,
) -> list[int]:
    """Return the optimal retained-index subsequence (tolerance mode)."""
    n = len(times)
    if n < 2:
        raise ValueError("at least two samples are required")

    reachable = _reachable(times, values, tolerance)
    dist = _minimum_segments(reachable, n)
    return _lexicographically_smallest_path(reachable, dist, n)


# ---------------------------------------------------------------------------
# Segment-budget mode (exact reduced-rational error)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SegmentReport:
    """Worst-deviation report for one retained segment."""

    start: int
    end: int
    error: Fraction
    #: Smallest intermediate index attaining ``error``; ``None`` when the
    #: segment connects adjacent samples (there is no intermediate point).
    witness: int | None


@dataclass(frozen=True)
class BudgetSolution:
    """Result of :func:`simplify_with_budget`."""

    indices: list[int]
    max_error: Fraction
    segments: list[SegmentReport]

    @property
    def segment_count(self) -> int:
        return len(self.indices) - 1


def vertical_deviation(
    t_i: int,
    v_i: int,
    t_j: int,
    v_j: int,
    t_k: int,
    v_k: int,
) -> Fraction:
    """Exact vertical distance of sample *k* from segment i-j.

        |v_k - (v_i + (v_j - v_i) * (t_k - t_i) / (t_j - t_i))|

    Returned as a reduced rational (``Fraction``); the cross product
    numerator is integer and the positive time span is the denominator.
    """
    dt = t_j - t_i
    numerator = (v_k - v_i) * dt - (v_j - v_i) * (t_k - t_i)
    if numerator < 0:
        numerator = -numerator
    return Fraction(numerator, dt)


def _edge_costs(
    times: list[int],
    values: list[int],
) -> tuple[list[list[Fraction | None]], list[list[int | None]]]:
    """Worst deviation and witness index for every possible segment.

    ``costs[i][j]`` is the maximum :func:`vertical_deviation` over the
    samples strictly between ``i`` and ``j`` (zero for adjacent nodes),
    and ``witnesses[i][j]`` is the *smallest* intermediate index
    attaining that maximum (``None`` when ``j == i + 1``).
    """
    n = len(times)
    costs: list[list[Fraction | None]] = [[None] * n for _ in range(n)]
    witnesses: list[list[int | None]] = [[None] * n for _ in range(n)]
    for i in range(n - 1):
        t_i = times[i]
        v_i = values[i]
        for j in range(i + 1, n):
            dt = times[j] - t_i
            dv = values[j] - v_i
            worst = Fraction(0)
            witness: int | None = None
            for k in range(i + 1, j):
                numerator = (values[k] - v_i) * dt - dv * (times[k] - t_i)
                if numerator < 0:
                    numerator = -numerator
                deviation = Fraction(numerator, dt)
                # Strict comparison keeps the first (smallest) index on
                # an exact tie.
                if witness is None or deviation > worst:
                    worst = deviation
                    witness = k
            costs[i][j] = worst
            witnesses[i][j] = witness
    return costs, witnesses


def _reachable_from_costs(
    costs: list[list[Fraction | None]],
    n: int,
    threshold: Fraction,
) -> list[int]:
    """Visibility masks containing exactly the edges with cost <= threshold."""
    reachable = [0] * n
    for i in range(n - 1):
        mask = 0
        row = costs[i]
        for j in range(i + 1, n):
            if row[j] <= threshold:
                mask |= 1 << j
        reachable[i] = mask
    return reachable


def _can_cover_within_budget(
    costs: list[list[Fraction | None]],
    n: int,
    budget: int,
    threshold: Fraction,
) -> bool:
    """Whether some endpoint path of <= budget edges has cost <= threshold."""
    infinity = n + 1
    dist = [infinity] * n
    dist[n - 1] = 0
    for i in range(n - 2, -1, -1):
        row = costs[i]
        best = infinity
        for j in range(i + 1, n):
            if row[j] <= threshold:
                candidate = dist[j] + 1
                if candidate < best:
                    best = candidate
                    if best == 1:  # direct edge i -> n-1, cannot beat it
                        break
        dist[i] = best
    return dist[0] <= budget


def simplify_with_budget(
    times: list[int],
    values: list[int],
    budget: int,
) -> BudgetSolution:
    """Minimise the worst vertical deviation using at most ``budget`` segments.

    The lexicographic tie-break applied after minimising the error is:

    1. use as few segments as possible at the same worst deviation;
    2. among those, keep the lexicographically smallest index sequence.

    The optimal deviation must equal some segment cost, so the sorted
    distinct segment costs are binary-searched with a feasibility DP
    (path of at most ``budget`` edges all within the candidate error).
    All rational comparisons go through ``Fraction`` (integer cross
    multiplication), so non-integer optima are found exactly instead of
    being rounded from an integer tolerance.
    """
    n = len(times)
    if n < 2:
        raise ValueError("at least two samples are required")
    if not isinstance(budget, int) or isinstance(budget, bool) or not (
        1 <= budget < n
    ):
        raise ValueError("budget must be an integer with 1 <= budget < len(points)")

    costs, witnesses = _edge_costs(times, values)

    candidates = sorted(
        {costs[i][j] for i in range(n - 1) for j in range(i + 1, n)}
    )
    lo, hi = 0, len(candidates) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if _can_cover_within_budget(costs, n, budget, candidates[mid]):
            hi = mid
        else:
            lo = mid + 1
    optimal_error = candidates[lo]

    # Resolve the two remaining tie-break levels on the optimal graph.
    reachable = _reachable_from_costs(costs, n, optimal_error)
    dist = _minimum_segments(reachable, n)
    indices = _lexicographically_smallest_path(reachable, dist, n)

    segments = [
        SegmentReport(
            start=a,
            end=b,
            error=costs[a][b],
            witness=witnesses[a][b],
        )
        for a, b in zip(indices, indices[1:])
    ]
    return BudgetSolution(
        indices=indices,
        max_error=optimal_error,
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Directional error mode (separate positive bounds above / below the chord)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectionalBounds:
    """Positive integer deviation bounds for the two error directions.

    A sample strictly *above* its interpolated chord must not deviate by
    more than ``above`` (scaled by the common multiplier in budget
    mode); a sample strictly *below* it must not deviate by more than
    ``below``.
    """

    above: int
    below: int


@dataclass(frozen=True)
class Witness:
    """An original point attaining a worst deviation, with its direction."""

    index: int
    #: One of :data:`ABOVE`, :data:`BELOW`, :data:`ON_LINE`.
    direction: str


@dataclass(frozen=True)
class DirectionalSegmentReport:
    """Worst-ratio report for one retained segment (directional mode)."""

    start: int
    end: int
    #: Segment bottleneck: the largest ``deviation / side-bound`` ratio.
    ratio: Fraction
    #: Smallest intermediate index attaining ``ratio`` with its direction;
    #: ``None`` when the segment connects adjacent samples.
    witness: Witness | None


@dataclass(frozen=True)
class DirectionalSolution:
    """Result of a directional solver.

    ``worst_ratio`` is ``1`` for threshold adjudication (every chosen
    segment fits at multiplier 1) and the minimised common multiplier
    for the budget solver.  ``witness`` is the original point attaining
    that worst ratio over the whole solution (smallest index on a tie,
    direction retained), or ``None`` when no segment has an
    intermediate point.
    """

    indices: list[int]
    worst_ratio: Fraction
    segments: list[DirectionalSegmentReport]
    witness: Witness | None

    @property
    def segment_count(self) -> int:
        return len(self.indices) - 1


def _validate_directional_bounds(
    above: int,
    below: int,
) -> DirectionalBounds:
    """Check that both directional limits are genuine positive ints."""
    for name, value in (("above", above), ("below", below)):
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError(f"{name} bound must be a positive integer")
    return DirectionalBounds(above=above, below=below)


def _edge_directional_costs(
    times: list[int],
    values: list[int],
    bounds: DirectionalBounds,
) -> tuple[list[list[Fraction | None]], list[list[Witness | None]]]:
    """Worst side-aware ratio and witness for every possible segment.

    For each intermediate sample the ratio is its deviation divided by
    the bound of the side it lies on::

        above: deviation / bounds.above
        below: deviation / bounds.below
        on:    0

    ``costs[i][j]`` is the maximum ratio on the segment (zero for
    adjacent nodes) and ``witnesses[i][j]`` is the smallest
    intermediate index attaining it together with that point's
    direction.  Everything is a :class:`Fraction` (integer cross
    multiplication on comparison), so boundary equality and non-integer
    multipliers are exact.
    """
    n = len(times)
    costs: list[list[Fraction | None]] = [[None] * n for _ in range(n)]
    witnesses: list[list[Witness | None]] = [[None] * n for _ in range(n)]
    for i in range(n - 1):
        t_i = times[i]
        v_i = values[i]
        for j in range(i + 1, n):
            dt = times[j] - t_i
            dv = values[j] - v_i
            worst = Fraction(0)
            witness: Witness | None = None
            for k in range(i + 1, j):
                signed = (values[k] - v_i) * dt - dv * (times[k] - t_i)
                if signed > 0:
                    ratio = Fraction(signed, dt * bounds.above)
                    direction = ABOVE
                elif signed < 0:
                    ratio = Fraction(-signed, dt * bounds.below)
                    direction = BELOW
                else:
                    ratio = Fraction(0)
                    direction = ON_LINE
                # Strict comparison keeps the first (smallest) index on
                # an exact ratio tie, even when the tied directions
                # differ (above-vs-below ties go to the smaller index).
                if witness is None or ratio > worst:
                    worst = ratio
                    witness = Witness(index=k, direction=direction)
            costs[i][j] = worst
            witnesses[i][j] = witness
    return costs, witnesses


def _build_directional_solution(
    indices: list[int],
    costs: list[list[Fraction | None]],
    witnesses: list[list[Witness | None]],
) -> DirectionalSolution:
    """Assemble segment reports and the global witness for one path.

    The global witness is the smallest original index attaining the
    path-wide worst ratio (segments are walked in order, and the
    per-segment witnesses already resolve within-segment ties by
    smallest index); its direction is reported with it.
    """
    segments: list[DirectionalSegmentReport] = []
    worst_ratio = Fraction(0)
    global_witness: Witness | None = None
    for a, b in zip(indices, indices[1:]):
        ratio = costs[a][b]
        witness = witnesses[a][b]
        segments.append(
            DirectionalSegmentReport(
                start=a, end=b, ratio=ratio, witness=witness
            )
        )
        # Promote on a strictly larger ratio; the first segment (in path
        # order) attaining the final maximum carries the globally
        # smallest attaining index.  Explicitly handling the very first
        # witness preserves the zero-ratio (collinear, direction "on")
        # point, matching the legacy budget witness convention.
        if witness is not None and (
            global_witness is None or ratio > worst_ratio
        ):
            worst_ratio = ratio
            global_witness = witness
    return DirectionalSolution(
        indices=indices,
        worst_ratio=worst_ratio,
        segments=segments,
        witness=global_witness,
    )


def simplify_directional(
    times: list[int],
    values: list[int],
    above: int,
    below: int,
) -> DirectionalSolution:
    """Fewest-segment polyline under two directional integer bounds.

    A candidate segment is admissible when every intermediate sample
    above the chord deviates by at most ``above`` and every one below
    it by at most ``below`` (boundary equality is admissible).  Ties are
    broken exactly as in the legacy mode: fewest segments, then the
    lexicographically smallest index sequence.
    """
    n = len(times)
    if n < 2:
        raise ValueError("at least two samples are required")
    bounds = _validate_directional_bounds(above, below)

    costs, witnesses = _edge_directional_costs(times, values, bounds)
    # Adjudication at multiplier 1: an edge fits iff its ratio <= 1.
    reachable = _reachable_from_costs(costs, n, Fraction(1))
    dist = _minimum_segments(reachable, n)
    indices = _lexicographically_smallest_path(reachable, dist, n)
    return _build_directional_solution(indices, costs, witnesses)


def simplify_with_budget_directional(
    times: list[int],
    values: list[int],
    budget: int,
    above: int,
    below: int,
) -> DirectionalSolution:
    """Minimise the common multiplier of the two directional bounds.

    With multiplier ``m`` every above-chord deviation must fit in
    ``m * above`` and every below-chord deviation in ``m * below``.  The
    solver finds the smallest reduced rational ``m`` for which some path
    of at most ``budget`` segments exists, then breaks ties by (1)
    fewest segments at that multiplier and (2) lexicographically
    smallest index sequence -- the same preference as
    :func:`simplify_with_budget`.  The optimum must equal some edge
    ratio, so the sorted distinct ratios are binary-searched with the
    same feasibility DP, and the returned witness is the original point
    attaining the worst multiplier together with its direction.
    """
    n = len(times)
    if n < 2:
        raise ValueError("at least two samples are required")
    if not isinstance(budget, int) or isinstance(budget, bool) or not (
        1 <= budget < n
    ):
        raise ValueError("budget must be an integer with 1 <= budget < len(points)")
    bounds = _validate_directional_bounds(above, below)

    costs, witnesses = _edge_directional_costs(times, values, bounds)

    candidates = sorted(
        {costs[i][j] for i in range(n - 1) for j in range(i + 1, n)}
    )
    lo, hi = 0, len(candidates) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if _can_cover_within_budget(costs, n, budget, candidates[mid]):
            hi = mid
        else:
            lo = mid + 1
    optimal_multiplier = candidates[lo]

    # Same reachable-path / shortest-path / lexicographic machinery.
    reachable = _reachable_from_costs(costs, n, optimal_multiplier)
    dist = _minimum_segments(reachable, n)
    indices = _lexicographically_smallest_path(reachable, dist, n)
    return _build_directional_solution(indices, costs, witnesses)
