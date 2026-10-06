"""Correctness tests for the directional-error solvers.

The oracle enumerates *every* subsequence containing both endpoints and
ranks it with the same preferences as the solvers, using exact integer
cross multiplication only:

* threshold mode -- admissible iff every segment's worst side-aware
  ratio ``deviation / bound`` is <= 1; then fewest segments, then
  lexicographically smallest index sequence;
* budget mode    -- minimise the path-wide worst ratio (the common
  multiplier), then fewest segments, then lexicographic order.

Both oracles also derive the global witness independently: the smallest
original index attaining the path-wide worst ratio, with the point's
own direction (above / below / on).  Explicit hand-picked cases guard
non-integer multipliers, above/below tie-breaking and boundary
equality.
"""

from __future__ import annotations

import itertools
import random
from fractions import Fraction
from math import gcd

import pytest

from app.simplifier import (
    ABOVE,
    BELOW,
    ON_LINE,
    simplify_directional,
    simplify_with_budget_directional,
    vertical_deviation,
)


# ---------------------------------------------------------------------------
# Exact brute-force oracle (unreduced integer pairs, never float)
# ---------------------------------------------------------------------------


def _edge_data(times, values, above, below):
    """Per edge: (ratio_num, ratio_den, witness_index, witness_direction)."""
    n = len(times)
    ratio_num = [[0] * n for _ in range(n)]
    ratio_den = [[1] * n for _ in range(n)]
    witness_idx = [[None] * n for _ in range(n)]
    witness_dir = [[None] * n for _ in range(n)]
    for a in range(n - 1):
        for b in range(a + 1, n):
            dt = times[b] - times[a]
            best_num, best_den = 0, 1
            wit, direction = None, None
            for k in range(a + 1, b):
                signed = (values[k] - values[a]) * dt - (
                    values[b] - values[a]
                ) * (times[k] - times[a])
                if signed > 0:
                    num, den, dirn = signed, dt * above, ABOVE
                elif signed < 0:
                    num, den, dirn = -signed, dt * below, BELOW
                else:
                    num, den, dirn = 0, dt, ON_LINE
                # strict > keeps the smallest index on an exact tie
                if wit is None or num * best_den > best_num * den:
                    best_num, best_den = num, den
                    wit, direction = k, dirn
            ratio_num[a][b] = best_num
            ratio_den[a][b] = best_den
            witness_idx[a][b] = wit
            witness_dir[a][b] = direction
    return ratio_num, ratio_den, witness_idx, witness_dir


def _all_subsequences(n):
    interior = list(range(1, n - 1))
    for chosen_mask in range(1 << (n - 2)):
        kept = [0]
        for k in interior:
            if chosen_mask >> (k - 1) & 1:
                kept.append(k)
        kept.append(n - 1)
        yield kept


def _path_worst(kept, ratio_num, ratio_den, witness_idx, witness_dir):
    """Worst ratio over a path and the smallest index attaining it."""
    worst_num, worst_den = 0, 1
    global_wit, global_dir = None, None
    for a, b in zip(kept, kept[1:]):
        num, den = ratio_num[a][b], ratio_den[a][b]
        # Promote on strict improvement; the first segment carrying an
        # intermediate witness (even at ratio 0, i.e. collinear) sets
        # it, matching the solver's "on" witness convention.
        if witness_idx[a][b] is not None and (
            global_wit is None or num * worst_den > worst_num * den
        ):
            worst_num, worst_den = num, den
            global_wit = witness_idx[a][b]
            global_dir = witness_dir[a][b]
    return worst_num, worst_den, global_wit, global_dir


def oracle_threshold(times, values, above, below):
    n = len(times)
    ratio_num, ratio_den, witness_idx, witness_dir = _edge_data(
        times, values, above, below
    )
    best = None
    for kept in _all_subsequences(n):
        if not all(
            ratio_num[a][b] * 1 <= 1 * ratio_den[a][b]
            for a, b in zip(kept, kept[1:])
        ):
            continue
        if best is None or len(kept) < len(best) or (
            len(kept) == len(best) and kept < best
        ):
            best = kept
    assert best is not None
    worst_num, worst_den, gwit, gdir = _path_worst(
        best, ratio_num, ratio_den, witness_idx, witness_dir
    )
    return best, Fraction(worst_num, worst_den), gwit, gdir


def oracle_budget(times, values, budget, above, below):
    n = len(times)
    ratio_num, ratio_den, witness_idx, witness_dir = _edge_data(
        times, values, above, below
    )
    best = None  # ((num, den), len(kept), kept)
    best_witness = (None, None)
    for kept in _all_subsequences(n):
        if len(kept) - 1 > budget:
            continue
        wn, wd, gwit, gdir = _path_worst(
            kept, ratio_num, ratio_den, witness_idx, witness_dir
        )
        key = ((wn, wd), len(kept), kept)
        if best is None or (
            wn * best[0][1] < best[0][0] * wd
            or (
                wn * best[0][1] == best[0][0] * wd
                and (len(kept), kept) < (best[1], best[2])
            )
        ):
            best = key
            best_witness = (gwit, gdir)
    assert best is not None
    return best[2], Fraction(best[0][0], best[0][1]), *best_witness


# ---------------------------------------------------------------------------
# Shared assertions
# ---------------------------------------------------------------------------


def assert_solution_matches(
    solution, times, values, above, below, expected_indices, expected_ratio,
    expected_witness, expected_direction,
):
    assert solution.indices == expected_indices
    assert solution.worst_ratio == expected_ratio
    # reduced rational, non-negative
    assert gcd(
        solution.worst_ratio.numerator, solution.worst_ratio.denominator
    ) == 1
    assert solution.worst_ratio.denominator > 0
    assert solution.worst_ratio.numerator >= 0

    # global witness
    if expected_witness is None:
        assert solution.witness is None
    else:
        assert solution.witness is not None
        assert solution.witness.index == expected_witness
        assert solution.witness.direction == expected_direction

    # per-segment reports re-derived by scanning every intermediate point
    for segment in zip(solution.segments,
                       zip(solution.indices, solution.indices[1:])):
        seg, (a, b) = segment
        assert (seg.start, seg.end) == (a, b)
        assert seg.ratio >= 0
        # recompute independently with the side-aware formula
        recomputed = []
        for k in range(a + 1, b):
            dev = vertical_deviation(
                times[a], values[a], times[b], values[b], times[k], values[k]
            )
            signed = (
                (values[k] - values[a]) * (times[b] - times[a])
                - (values[b] - values[a]) * (times[k] - times[a])
            )
            if signed > 0:
                ratio = dev / above
                dirn = ABOVE
            elif signed < 0:
                ratio = dev / below
                dirn = BELOW
            else:
                ratio, dirn = Fraction(0), ON_LINE
            recomputed.append((k, ratio, dirn))
        assert seg.ratio == max(
            (r for _, r, _ in recomputed), default=Fraction(0)
        )
        if seg.witness is None:
            assert b == a + 1
        else:
            attaining = [
                (k, dirn)
                for k, ratio, dirn in recomputed
                if ratio == seg.ratio
            ]
            smallest_index, smallest_dir = min(attaining, key=lambda t: t[0])
            assert seg.witness.index == smallest_index
            assert seg.witness.direction == smallest_dir

    # the reported global witness really attains the path-wide ratio
    if solution.witness is not None:
        idx = solution.witness.index
        owning = next(
            seg for seg in solution.segments
            if seg.start < idx < seg.end
        )
        assert owning.ratio == solution.worst_ratio
        assert owning.witness.index == idx
        # smallest attaining index over the whole solution
        all_attaining = [
            seg.witness.index
            for seg in solution.segments
            if seg.witness is not None and seg.ratio == solution.worst_ratio
        ]
        assert idx == min(all_attaining)


def assert_threshold_matches(times, values, above, below):
    solution = simplify_directional(times, values, above, below)
    indices, ratio, wit, dirn = oracle_threshold(
        times, values, above, below
    )
    assert_solution_matches(
        solution, times, values, above, below, indices, ratio, wit, dirn
    )
    # threshold adjudication always lands within multiplier 1
    assert solution.worst_ratio <= 1
    return solution


def assert_budget_matches(times, values, budget, above, below):
    solution = simplify_with_budget_directional(
        times, values, budget, above, below
    )
    indices, ratio, wit, dirn = oracle_budget(
        times, values, budget, above, below
    )
    assert_solution_matches(
        solution, times, values, above, below, indices, ratio, wit, dirn
    )
    return solution


# ---------------------------------------------------------------------------
# Hand-picked: non-integer multipliers
# ---------------------------------------------------------------------------


def test_threshold_two_points_fit_any_bounds():
    solution = simplify_directional([0, 10], [5, -5], 1, 1)
    assert solution.indices == [0, 1]
    assert solution.worst_ratio == 0
    assert solution.witness is None


def test_threshold_rejects_segment_exceeding_the_tight_below_bound():
    # chord 0->3 is flat; point 1 is +3 above (3/10 of its bound),
    # point 2 is -3 below (3/2 > 1), so the chord is inadmissible and
    # the solution must split.
    times = [0, 1, 2, 3]
    values = [0, 3, -3, 0]
    solution = assert_threshold_matches(times, values, 10, 2)
    assert solution.indices == [0, 2, 3]


def test_threshold_boundary_equality_is_admissible_above_and_below():
    # Points land exactly on deviation == bound on both sides.
    times = [0, 1, 2, 3]
    values = [0, 4, -4, 0]
    solution = simplify_directional(times, values, 4, 4)
    assert solution.indices == [0, 3]
    # worst ratio exactly 1; smallest attaining index (1, above) witnesses
    assert solution.worst_ratio == 1
    assert solution.witness.index == 1
    assert solution.witness.direction == ABOVE


def test_threshold_boundary_with_non_unit_time_spans_is_exact():
    # chord (0,0)->(4,0); at t=1 value 2 -> deviation 2 exactly equals
    # the above bound 2 (ratio 1, inclusive boundary).
    times = [0, 1, 4]
    values = [0, 2, 0]
    solution = simplify_directional(times, values, 2, 5)
    assert solution.indices == [0, 2]
    assert solution.worst_ratio == 1
    assert solution.witness.direction == ABOVE


def test_threshold_one_unit_beyond_boundary_is_rejected():
    times = [0, 1, 2]
    values = [0, 3, 0]
    # 3 <= 3 fits ...
    assert simplify_directional(times, values, 3, 3).indices == [0, 2]
    # ... but 3 > 2 does not; both segments are needed.
    assert simplify_directional(times, values, 2, 2).indices == [0, 1, 2]


def test_budget_non_integer_multiplier_is_exact():
    # flat chord 0 -> 2 over dt = 2: the above point has cross product
    # 2, hence deviation 1/2.  With above bound 3 the segment ratio is
    # (1/2)/3 = 1/3 -- a non-integer multiplier found exactly.
    solution = simplify_with_budget_directional(
        [0, 1, 2], [0, 1, 0], 1, 3, 10
    )
    assert solution.indices == [0, 2]
    assert solution.worst_ratio == Fraction(1, 3)
    assert solution.witness.index == 1
    assert solution.witness.direction == ABOVE


def test_budget_non_integer_with_irregular_times():
    # chord (0,0)->(4,0): above point (t=1, v=3) has deviation 3 and
    # above bound 2 -> ratio 3/2; below point (t=2, v=-2) with bound 5
    # has ratio 2/5; the bottleneck is the non-integer 3/2.
    times = [0, 1, 2, 4]
    values = [0, 3, -2, 0]
    solution = assert_budget_matches(times, values, 1, 2, 5)
    assert solution.indices == [0, 3]
    assert solution.worst_ratio == Fraction(3, 2)
    assert solution.witness.index == 1
    assert solution.witness.direction == ABOVE


def test_budget_asymmetric_bounds_pick_the_tight_side():
    # deviation 3 on both sides; bound 1 above vs 2 below -> the above
    # point alone decides the multiplier 3 (below would allow 3/2).
    times = [0, 1, 2, 3]
    values = [0, 3, -3, 0]
    solution = assert_budget_matches(times, values, 1, 1, 2)
    assert solution.indices == [0, 3]
    assert solution.worst_ratio == 3
    assert solution.witness.index == 1
    assert solution.witness.direction == ABOVE


def test_budget_collinear_zero_multiplier_witness_is_on_line():
    solution = simplify_with_budget_directional(
        [0, 1, 2, 3], [2, 5, 8, 11], 1, 1, 1
    )
    assert solution.indices == [0, 3]
    assert solution.worst_ratio == 0
    assert solution.witness.index == 1
    assert solution.witness.direction == ON_LINE


def test_budget_full_budget_all_adjacent_has_null_witness():
    solution = simplify_with_budget_directional(
        [0, 1, 2], [0, 5, 0], 2, 1, 1
    )
    assert solution.indices == [0, 1, 2]
    assert solution.worst_ratio == 0
    assert solution.witness is None
    assert all(seg.witness is None for seg in solution.segments)


# ---------------------------------------------------------------------------
# Hand-picked: above/below tie-breaking
# ---------------------------------------------------------------------------


def test_above_below_tie_keeps_smaller_index_above_wins():
    # flat chord: index 1 above at 2, index 2 below at -2; equal bounds.
    # Both attain ratio 2; the smallest index (1, above) is the witness.
    times = [0, 1, 2, 3]
    values = [0, 2, -2, 0]
    solution = simplify_with_budget_directional(
        times, values, 1, 1, 1
    )
    assert solution.indices == [0, 3]
    assert solution.worst_ratio == 2
    assert solution.witness.index == 1
    assert solution.witness.direction == ABOVE
    # the per-segment witness agrees and resolves the tie by index too
    assert solution.segments[0].witness.index == 1
    assert solution.segments[0].witness.direction == ABOVE


def test_above_below_tie_with_smaller_index_below():
    # index 1 below, index 2 above at equal deviations: below wins by
    # index, proving the direction is retained rather than defaulted.
    times = [0, 1, 2, 3]
    values = [0, -2, 2, 0]
    solution = simplify_with_budget_directional(
        times, values, 1, 1, 1
    )
    assert solution.witness.index == 1
    assert solution.witness.direction == BELOW


def test_tie_across_segments_global_witness_is_smallest_index():
    # Solution path 0 -> 2 -> 4: each segment ties at ratio 1; the
    # global witness is the smallest attaining index across the path.
    times = [0, 1, 2, 3, 4]
    values = [0, 3, 0, 3, 0]  # peaks of height 3 at indices 1 and 3
    solution = simplify_directional(times, values, 3, 3)
    assert solution.indices == [0, 4]
    assert solution.witness.index == 1


def test_lexicographic_tie_break_is_unchanged_under_direction():
    # Mirrors the legacy sawtooth tie case: with bounds of 4 the flat
    # chord fails at the peaks (ratio 5/4 > 1) while splits do not, so
    # the two-segment solutions [0,1,6] and [0,5,6] both fit at ratio 1
    # and the lexicographically smallest [0,1,6] must win.
    times = list(range(7))
    values = [0, 5, 0, 5, 0, 5, 0]
    solution = simplify_directional(times, values, 4, 4)
    assert solution.indices == [0, 1, 6]
    # on segment 1 -> 6 the first valley (index 2) attains ratio 1 and
    # is below the chord; it is the smallest attaining index overall.
    assert solution.witness.index == 2
    assert solution.witness.direction == BELOW


def test_directional_bounds_change_which_direction_binds():
    # Same geometry, tighter above bound: the multiplier changes and is
    # driven by the above point.
    times = [0, 1, 2, 3]
    values = [0, 3, -3, 0]
    tight_above = simplify_with_budget_directional(times, values, 1, 1, 3)
    tight_below = simplify_with_budget_directional(times, values, 1, 3, 1)
    assert tight_above.worst_ratio == 3
    assert tight_above.witness.direction == ABOVE
    assert tight_below.worst_ratio == 3
    assert tight_below.witness.direction == BELOW


# ---------------------------------------------------------------------------
# Invalid arguments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "above, below",
    [(0, 1), (1, 0), (-1, 1), (1, -2), (1.0, 1), (1, True), (False, 1)],
)
def test_invalid_bounds_raise(above, below):
    times, values = [0, 1, 2], [0, 1, 0]
    with pytest.raises(ValueError):
        simplify_directional(times, values, above, below)
    with pytest.raises(ValueError):
        simplify_with_budget_directional(times, values, 1, above, below)


def test_directional_budget_rejects_invalid_budget():
    times, values = [0, 1, 2, 3], [0, 1, 0, 1]
    for bad in (0, -1, 4, 5, 1.0, True):
        with pytest.raises(ValueError):
            simplify_with_budget_directional(times, values, bad, 1, 1)


# ---------------------------------------------------------------------------
# Enumerative cross-checks
# ---------------------------------------------------------------------------


def test_exhaustive_all_small_ternary_trajectories():
    """Every value sequence over {-1,0,1}, length 2..7, small bounds."""
    bound_pairs = [(1, 1), (1, 2), (2, 1), (3, 2)]
    for n in range(2, 8):
        times = list(range(n))
        for values in itertools.product((-1, 0, 1), repeat=n):
            for above, below in bound_pairs:
                assert_threshold_matches(times, list(values), above, below)
                for budget in range(1, n):
                    assert_budget_matches(
                        times, list(values), budget, above, below
                    )


def test_exhaustive_randomized_small_cases():
    """Random tiny trajectories with irregular times and varied bounds."""
    rng = random.Random(20240917)
    for _ in range(250):
        n = rng.randint(2, 9)
        times = sorted(rng.sample(range(60), n))
        values = [rng.randint(-8, 8) for _ in range(n)]
        above = rng.randint(1, 6)
        below = rng.randint(1, 6)
        assert_threshold_matches(times, values, above, below)
        assert_budget_matches(
            times, values, rng.randint(1, n - 1), above, below
        )


def test_non_integer_optima_actually_occur_in_directional_mode():
    """Guard the suite: enumerated directional optima have denom > 1."""
    found = False
    for above in (2, 3):
        for values in itertools.product(range(-2, 3), repeat=3):
            solution = simplify_with_budget_directional(
                [0, 1, 2], list(values), 1, above, 5
            )
            if solution.worst_ratio.denominator > 1:
                found = True
    assert found


def test_large_instance_stays_exact_and_within_budget():
    rng = random.Random(424299)
    n = 120
    times = sorted(rng.sample(range(10**9), n))
    values = [rng.randint(-10**6, 10**6) for _ in range(n)]
    solution = simplify_with_budget_directional(times, values, 10, 7, 11)
    assert solution.indices[0] == 0 and solution.indices[-1] == n - 1
    assert solution.segment_count <= 10
    assert all(seg.ratio <= solution.worst_ratio for seg in solution.segments)
    assert any(
        seg.ratio == solution.worst_ratio
        for seg in solution.segments if seg.witness is not None
    )
    assert solution.witness.direction in (ABOVE, BELOW, ON_LINE)


# ---------------------------------------------------------------------------
# Extra boundary / tie cases requested by the problem statement
# ---------------------------------------------------------------------------


def test_threshold_irregular_time_boundary_equality_is_exact():
    # chord (0,0)->(5,0): above point at t=2 with value 3 deviates 3,
    # below point at t=3 with value -4 deviates 4; bounds (3, 4) make
    # the segment fit with both ratios exactly equal to 1.
    times = [0, 2, 3, 5]
    values = [0, 3, -4, 0]
    solution = assert_threshold_matches(times, values, 3, 4)
    assert solution.indices == [0, 3]
    assert solution.worst_ratio == 1
    assert solution.witness.index == 1
    assert solution.witness.direction == ABOVE


def test_threshold_irregular_time_one_unit_beyond_forces_split():
    times = [0, 2, 3, 5]
    values = [0, 3, -4, 0]
    # above bound 2 -> ratio 3/2 > 1, chord rejected.  Segment 1 -> 3
    # is rejected too (the below point is outside), so every sample
    # must be retained.
    solution = simplify_directional(times, values, 2, 4)
    assert solution.indices == [0, 1, 2, 3]


def test_budget_above_below_tie_across_two_segments():
    """Guard: cases exist where the optimal path's worst ratio is tied
    between an above point on one segment and a below point on another;
    the globally smallest attaining index (with its own direction) must
    be reported.  Search short trajectories and verify against the
    oracle whenever such a case occurs.
    """
    found = False
    rng = random.Random(7711)
    for _ in range(400):
        n = rng.randint(4, 7)
        times = list(range(n))
        values = [rng.randint(-4, 4) for _ in range(n)]
        above = below = rng.randint(1, 4)
        solution = simplify_with_budget_directional(
            times, values, n - 2, above, below
        )
        worst_segments = [
            seg for seg in solution.segments
            if seg.witness is not None and seg.ratio == solution.worst_ratio
        ]
        sides = {seg.witness.direction for seg in worst_segments}
        if (
            solution.worst_ratio > 0
            and len(worst_segments) >= 2
            and {ABOVE, BELOW} <= sides
        ):
            found = True
            # oracle agreement (indices, multiplier, witness, direction)
            assert_budget_matches(times, values, n - 2, above, below)
            # global witness is the smallest attaining index overall
            assert solution.witness.index == min(
                seg.witness.index for seg in worst_segments
            )
            owning = next(
                seg.witness
                for seg in worst_segments
                if seg.witness.index == solution.witness.index
            )
            assert solution.witness.direction == owning.direction
            break
    assert found, "random search should encounter cross-side ties"


def test_budget_zero_one_half_are_exact_multipliers():
    # zero multiplier (collinear) and a half multiplier in one family
    assert simplify_with_budget_directional(
        [0, 1, 2], [0, 1, 2], 1, 3, 3
    ).worst_ratio == Fraction(0)
    # deviation 1 against bound 2 with unit time span -> 1/2 exactly
    solution = simplify_with_budget_directional(
        [0, 1], [0, 1], 1, 2, 2
    )
    assert solution.worst_ratio == 0  # no intermediate point
    solution = simplify_with_budget_directional(
        [0, 1, 2], [0, 1, 0], 1, 2, 2
    )
    # deviation 1 (cross 2/dt 2) over bound 2 -> 1/2
    assert solution.worst_ratio == Fraction(1, 2)


def test_budget_zero_multiplier_needs_all_segments():
    # A jagged trajectory cannot be made collinear by any split short of
    # keeping every adjacent segment; at multiplier 0 the feasible graph
    # contains only collinear edges, so the optimum is the full path.
    times = [0, 1, 2, 3]
    values = [0, 1, 0, 1]
    solution = simplify_with_budget_directional(times, values, 3, 100, 100)
    assert solution.indices == [0, 1, 2, 3]
    assert solution.worst_ratio == 0
    assert solution.witness is None

    # The same geometry with budget 2 must instead pay a positive
    # non-integer multiplier (the 2/3 end-to-end chord bottleneck).
    tight = simplify_with_budget_directional(times, values, 2, 1, 1)
    assert tight.segment_count <= 2
    assert tight.worst_ratio == Fraction(2, 3)
    assert tight.witness.direction in (ABOVE, BELOW)


def test_symmetric_bounds_above_and_below_points_share_ratio():
    times = [0, 1, 2, 3]
    values = [0, 2, -2, 0]
    above_solution = simplify_with_budget_directional(
        times, values, 1, 2, 2
    )
    # mirrored trajectory swaps the sides but yields the same multiplier
    mirrored = simplify_with_budget_directional(
        times, [-v for v in values], 1, 2, 2
    )
    assert above_solution.worst_ratio == mirrored.worst_ratio == 1
    assert above_solution.witness.direction == ABOVE
    assert mirrored.witness.direction == BELOW
    # smallest index is 1 in both cases
    assert above_solution.witness.index == mirrored.witness.index == 1
