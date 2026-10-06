"""Correctness tests for the segment-budget rational solver.

The oracle enumerates *every* subsequence that contains both endpoints
and keeps at most ``budget`` segments, evaluates its worst vertical
deviation as an exact reduced rational, and applies the same
three-level preference as the solver:

  1. smallest worst deviation (compared by integer cross multiplication
     via :class:`fractions.Fraction`);
  2. fewest segments at that deviation;
  3. lexicographically smallest index sequence.

The reported per-segment witnesses are checked independently as well.
"""

from __future__ import annotations

import itertools
import random
from fractions import Fraction

import pytest

from app.simplifier import simplify_with_budget, vertical_deviation


# ---------------------------------------------------------------------------
# Exact brute-force oracle
# ---------------------------------------------------------------------------


def brute_force_budget(times, values, budget):
    """Return (indices, max_error, per-segment reports) for the optimum.

    Edge costs are precomputed once as unreduced ``(numerator,
    denominator)`` pairs; every subsequence is ranked by integer cross
    multiplication, so the hot enumeration loop never constructs a
    :class:`Fraction`.
    """
    n = len(times)
    interior = list(range(1, n - 1))

    # costs[a][b] = (num, den, witness) for the worst deviation on a->b.
    edge_num: list[list[int]] = [[0] * n for _ in range(n)]
    edge_den: list[list[int]] = [[1] * n for _ in range(n)]
    edge_wit: list[list[int | None]] = [[None] * n for _ in range(n)]
    for a in range(n - 1):
        for b in range(a + 1, n):
            den = times[b] - times[a]
            worst_num = 0
            witness = None
            for k in range(a + 1, b):
                num = (values[k] - values[a]) * den - (
                    values[b] - values[a]
                ) * (times[k] - times[a])
                if num < 0:
                    num = -num
                # strict > keeps the smallest index on a tie
                if witness is None or num > worst_num:
                    worst_num = num
                    witness = k
            edge_num[a][b] = worst_num
            edge_den[a][b] = den
            edge_wit[a][b] = witness

    def less_pair(num1, den1, num2, den2):
        return num1 * den2 < num2 * den1

    best = None  # ((max_num, max_den), len(kept), kept)
    for chosen_mask in range(1 << (n - 2)):
        kept = [0]
        for k in interior:
            if chosen_mask >> (k - 1) & 1:
                kept.append(k)
        kept.append(n - 1)
        if len(kept) - 1 > budget:
            continue

        max_num, max_den = 0, 1
        for a, b in zip(kept, kept[1:]):
            num, den = edge_num[a][b], edge_den[a][b]
            if less_pair(max_num, max_den, num, den):
                max_num, max_den = num, den

        key = ((max_num, max_den), len(kept), kept)
        if best is None or (
            less_pair(key[0][0], key[0][1], best[0][0], best[0][1])
            or (
                not less_pair(
                    best[0][0], best[0][1], key[0][0], key[0][1]
                )
                and (key[1], key[2]) < (best[1], best[2])
            )
        ):
            best = key

    assert best is not None
    kept = best[2]
    max_error = Fraction(best[0][0], best[0][1])
    reports = [
        (a, b, Fraction(edge_num[a][b], edge_den[a][b]), edge_wit[a][b])
        for a, b in zip(kept, kept[1:])
    ]
    return kept, max_error, reports


def assert_matches_oracle(times, values, budget):
    solution = simplify_with_budget(times, values, budget)
    expected_indices, expected_error, expected_reports = brute_force_budget(
        times, values, budget
    )
    assert solution.indices == expected_indices
    assert solution.max_error == expected_error
    assert solution.segment_count == len(expected_indices) - 1
    assert solution.max_error.denominator > 0
    assert solution.max_error.numerator >= 0
    # reduced rational
    from math import gcd

    assert gcd(solution.max_error.numerator, solution.max_error.denominator) == 1

    # per-segment error/witness consistency
    for segment, (a, b, error, witness) in zip(solution.segments, expected_reports):
        assert (segment.start, segment.end) == (a, b)
        assert segment.error == error
        assert segment.witness == witness
        # recompute witness by scanning every intermediate point
        if witness is not None:
            for k in range(a + 1, b):
                dev = vertical_deviation(
                    times[a], values[a], times[b], values[b], times[k], values[k]
                )
                assert dev <= segment.error
                if k < witness:
                    assert dev < segment.error  # earlier index cannot tie
            assert segment.witness == min(
                k
                for k in range(a + 1, b)
                if vertical_deviation(
                    times[a], values[a], times[b], values[b], times[k], values[k]
                )
                == segment.error
            )
        else:
            assert b == a + 1
    return solution


# ---------------------------------------------------------------------------
# Hand-picked cases
# ---------------------------------------------------------------------------


def test_two_points_zero_error_without_witness():
    solution = simplify_with_budget([0, 10], [5, -5], 1)
    assert solution.indices == [0, 1]
    assert solution.max_error == Fraction(0)
    assert solution.segment_count == 1
    assert solution.segments[0].witness is None
    assert solution.segments[0].error == Fraction(0)


def test_collinear_collapses_to_endpoints_with_zero_error():
    times = [0, 1, 2, 3, 4]
    values = [2, 5, 8, 11, 14]
    solution = assert_matches_oracle(times, values, 1)
    assert solution.indices == [0, 4]
    assert solution.max_error == 0
    # zero-error tie among intermediates keeps the smallest index
    assert solution.segments[0].witness == 1


def test_full_budget_keeps_every_sample_with_zero_error():
    times = list(range(7))
    values = [0, 5, 0, 5, 0, 5, 0]
    solution = assert_matches_oracle(times, values, 6)
    assert solution.indices == list(range(7))
    assert solution.max_error == 0
    assert all(segment.witness is None for segment in solution.segments)


def test_non_integer_optimum_is_returned_exactly_not_rounded():
    """The optimum is 1/2; an integer tolerance round-up would hide it."""
    solution = simplify_with_budget([0, 1, 2], [0, 0, 1], 1)
    assert solution.indices == [0, 2]
    assert solution.max_error == Fraction(1, 2)
    assert solution.segments[0].witness == 1


def test_optimum_uses_fewer_segments_than_budget_allows():
    """Primary objective is error; a single segment can dominate here.

    values [0,1,0,1], budget 2: the end-to-end chord has worst error
    2/3 while every two-segment split has a segment with error 1, so the
    unique optimum uses one segment (the second tie-break level).
    """
    solution = simplify_with_budget([0, 1, 2, 3], [0, 1, 0, 1], 2)
    assert solution.indices == [0, 3]
    assert solution.segment_count == 1
    assert solution.max_error == Fraction(2, 3)
    assert solution.segments[0].witness == 1  # points 1 and 3 tie at 2/3


def test_lexicographically_smallest_sequence_at_optimal_error():
    """Splits at index 2 and at index 4 both attain the 3/4 optimum."""
    times = list(range(7))
    values = [0, 0, 1, 0, 1, 0, 0]
    solution = assert_matches_oracle(times, values, 2)
    assert solution.indices == [0, 2, 6]
    assert solution.max_error == Fraction(3, 4)
    assert solution.segments[1].witness == 3


def test_witness_is_smallest_index_on_exact_tie():
    """Flat chord with two equally distant intermediate points."""
    solution = simplify_with_budget([0, 1, 2, 3], [0, 1, 1, 0], 1)
    assert solution.max_error == 1
    assert solution.segments[0].witness == 1


def test_witness_with_non_unit_time_spans_uses_rational_error():
    # chord (0,0)->(5,0): point at t=2 has value 1 -> deviation 1.
    # point at t=3 has value 1 -> deviation 1; smallest index wins.
    times = [0, 2, 3, 5]
    values = [0, 1, 1, 0]
    solution = assert_matches_oracle(times, values, 1)
    assert solution.indices == [0, 3]
    assert solution.max_error == 1
    assert solution.segments[0].witness == 1


def test_irregular_times_yield_non_integer_error():
    # (0,0)->(4,10), point at t=1 with value 1:
    # interp = 10/4 = 5/2, deviation = 3/2.
    solution = simplify_with_budget([0, 1, 4], [0, 1, 10], 1)
    assert solution.max_error == Fraction(3, 2)
    assert solution.segments[0].witness == 1


def test_largest_inputs_stay_exact():
    times = [0, 10**9 // 3, 2 * 10**9 // 3, 10**9]
    values = [10**6, -10**6, 10**6, -10**6]
    solution = simplify_with_budget(times, values, 3)
    assert solution.indices == [0, 1, 2, 3]
    assert solution.max_error == 0


# ---------------------------------------------------------------------------
# Enumerative cross-checks
# ---------------------------------------------------------------------------


def test_exhaustive_all_small_ternary_trajectories():
    """Every value sequence over {-1,0,1}, length 2..7, every budget."""
    for n in range(2, 8):
        times = list(range(n))
        for values in itertools.product((-1, 0, 1), repeat=n):
            for budget in range(1, n):
                assert_matches_oracle(times, list(values), budget)


def test_exhaustive_randomized_small_cases():
    """Random tiny trajectories with irregular integer times."""
    rng = random.Random(98765)
    for _ in range(300):
        n = rng.randint(2, 9)
        times = sorted(rng.sample(range(60), n))
        values = [rng.randint(-12, 12) for _ in range(n)]
        budget = rng.randint(1, n - 1)
        assert_matches_oracle(times, values, budget)


def test_non_integer_optima_actually_occur():
    """Guard the test suite itself: some enumerated optima have denom > 1."""
    times = [0, 1, 3]
    found_fractional = False
    for values in itertools.product(range(-2, 3), repeat=3):
        solution = simplify_with_budget(times, list(values), 1)
        if solution.max_error.denominator > 1:
            found_fractional = True
    assert found_fractional


def test_invalid_budget_raises():
    times = list(range(5))
    values = [0, 0, 1, 0, 0]
    for bad in (0, -1, 5, 6):
        with pytest.raises(ValueError):
            simplify_with_budget(times, values, bad)


def test_budget_boundary_equals_n_minus_one_and_one():
    rng = random.Random(4242)
    for _ in range(60):
        n = rng.randint(2, 13)
        times = sorted(rng.sample(range(1000), n))
        values = [rng.randint(-20, 20) for _ in range(n)]
        for budget in (1, n - 1):
            assert_matches_oracle(times, values, budget)


def test_large_instances_still_solve_exactly():
    """The solver is exact and fast beyond enumeration range (n <= 120)."""
    rng = random.Random(31337)
    n = 120
    times = sorted(rng.sample(range(10**9), n))
    values = [rng.randint(-10**6, 10**6) for _ in range(n)]
    for budget in (1, 10):
        solution = simplify_with_budget(times, values, budget)
        assert solution.indices[0] == 0 and solution.indices[-1] == n - 1
        assert solution.segment_count <= budget
        # returned max_error really is the bottleneck of its segments
        from math import gcd

        assert gcd(solution.max_error.numerator, solution.max_error.denominator) == 1
        assert all(segment.error <= solution.max_error for segment in solution.segments)
        assert any(segment.error == solution.max_error for segment in solution.segments)
