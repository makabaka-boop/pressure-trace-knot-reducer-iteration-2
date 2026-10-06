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

Every comparison is performed with integer cross multiplication
(:class:`fractions.Fraction` reduces the result exactly); no floating
point arithmetic is involved.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction


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
