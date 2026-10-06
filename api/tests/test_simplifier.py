"""Correctness tests for the integer-only optimal simplifier."""

from __future__ import annotations

import itertools
import random

from app.simplifier import simplify, within_segment


def brute_force_optimum(times, values, tolerance):
    """Enumerate every endpoint-covering subsequence and return the best.

    A subsequence is a subset of the interior indices; validity means
    every skipped sample lies inside the error corridor of its segment.
    Ties are broken by the lexicographically smallest full index list.
    """
    n = len(times)
    interior = range(1, n - 1)
    best = None
    for chosen_mask in range(1 << (n - 2)):
        kept = [0]
        for offset, k in enumerate(interior, start=1):
            if chosen_mask >> (k - 1) & 1:
                kept.append(k)
        kept.append(n - 1)

        valid = True
        for a, b in zip(kept, kept[1:]):
            for k in range(a + 1, b):
                if not within_segment(
                    times[a], values[a],
                    times[b], values[b],
                    times[k], values[k],
                    tolerance,
                ):
                    valid = False
                    break
            if not valid:
                break
        if valid and (best is None or len(kept) < len(best)
                      or (len(kept) == len(best) and kept < best)):
            best = kept
    assert best is not None
    return best


def test_two_points_are_always_kept():
    assert simplify([0, 10], [5, -5], tolerance=0) == [0, 1]


def test_collinear_points_collapse_to_endpoints_at_zero_tolerance():
    times = [0, 1, 2, 3, 4]
    values = [2, 5, 8, 11, 14]  # slope 3
    assert simplify(times, values, tolerance=0) == [0, 4]


def test_jagged_values_keep_all_points_at_zero_tolerance():
    times = [0, 1, 2, 3]
    values = [0, 1, 0, 1]
    assert simplify(times, values, tolerance=0) == [0, 1, 2, 3]


def test_large_tolerance_keeps_only_endpoints():
    times = list(range(10))
    values = [0, 100, -100, 99, -99, 0, 50, -50, 1, 0]
    assert simplify(times, values, tolerance=10**6) == [0, 9]


def test_result_contains_endpoints_and_runs_increasing():
    rng = random.Random(4242)
    for _ in range(25):
        n = rng.randint(2, 20)
        times = sorted(rng.sample(range(1000), n))
        values = [rng.randint(-100, 100) for _ in range(n)]
        tolerance = rng.randint(0, 20)
        result = simplify(times, values, tolerance)
        assert result[0] == 0
        assert result[-1] == n - 1
        assert result == sorted(set(result))


def test_exhaustive_all_small_ternary_trajectories():
    """Every value sequence over {-1, 0, 1}, length 2..7, tol 0..2."""
    for n in range(2, 8):
        times = list(range(n))
        for values in itertools.product((-1, 0, 1), repeat=n):
            for tolerance in range(3):
                expected = brute_force_optimum(times, list(values), tolerance)
                assert simplify(times, list(values), tolerance) == expected, (
                    values, tolerance
                )


def test_exhaustive_randomized_small_cases():
    """Random tiny cases compared against full subsequence enumeration."""
    rng = random.Random(123456)
    for _ in range(400):
        n = rng.randint(2, 9)
        times = sorted(rng.sample(range(60), n))
        values = [rng.randint(-12, 12) for _ in range(n)]
        tolerance = rng.randint(0, 6)
        expected = brute_force_optimum(times, values, tolerance)
        assert simplify(times, values, tolerance) == expected


def test_pointwise_greedy_can_use_more_segments_than_optimum():
    """The farthest-reaching greedy choice is not globally optimal.

    values = [-2, -1, -1, -2, 0, -1], tolerance = 1: greedy jumps
    0 -> 3 first and needs three segments, while 0 -> 1 -> 5 covers the
    whole trajectory in two.  This is why the solver uses shortest-path
    DP on the visibility graph instead of greedy scanning.
    """
    times = [0, 1, 2, 3, 4, 5]
    values = [-2, -1, -1, -2, 0, -1]
    assert simplify(times, values, tolerance=1) == [0, 1, 5]


def test_lexicographically_smallest_sequence_breaks_ties():
    """Several shortest solutions exist; the smallest index list wins.

    End-to-end flat segment fails by one cross-product unit at every
    peak.  The two-segment solutions are [0,1,6] and [0,5,6], so the
    answer must be [0, 1, 6].
    """
    times = [0, 1, 2, 3, 4, 5, 6]
    values = [0, 5, 0, 5, 0, 5, 0]
    assert simplify(times, values, tolerance=4) == [0, 1, 6]


def test_intermediate_failure_does_not_permit_early_break():
    """A point outside the corridor followed by one back inside it.

    The segment 0 -> 3 must be rejected even though the last interior
    point fits; only a full check of all intermediates gives the right
    answer.
    """
    times = [0, 1, 2, 3]
    values = [0, 0, 5, 0]  # point 2 is far off the end-to-end line
    assert simplify(times, values, tolerance=1) == [0, 1, 2, 3]


def test_integer_cross_multiply_is_exact_near_boundary():
    """Two checks differing by exactly one cross-product unit.

    Segment (0, 0) -> (10^9, 1): the interpolated value at t=1 is
    10^-9.  With tolerance 1 the allowed cross-product budget is 10^9.

    * value 1   -> cross deviation 10^9 - 1 = 999_999_999 <= budget
    * value 2   -> cross deviation 2*10^9 - 1            >  budget
    """
    args_base = (0, 0, 10**9, 1, 1)
    assert within_segment(*args_base, 1, 1) is True
    assert within_segment(*args_base, 2, 1) is False
    # And the boundary itself is inclusive.
    assert within_segment(0, 0, 3, 0, 1, 0, 0) is True  # deviation 0
    assert within_segment(0, 0, 3, 3, 1, 2, 1) is True   # deviation exactly tol
    assert within_segment(0, 0, 3, 3, 1, 3, 1) is False  # one value unit beyond


def test_largest_allowed_inputs_stay_exact():
    times = [0, 10**9 // 3, 2 * 10**9 // 3, 10**9]
    values = [10**6, -10**6, 10**6, -10**6]
    result = simplify(times, values, tolerance=10**6)
    assert result[0] == 0 and result[-1] == 3
