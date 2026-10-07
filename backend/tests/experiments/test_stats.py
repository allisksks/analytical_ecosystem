"""Statistical core vs reference implementations (SciPy, statsmodels) — TZ requires 100% coverage here."""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats as st
from statsmodels.stats.power import NormalIndPower, TTestIndPower
from statsmodels.stats.proportion import proportion_effectsize, proportions_ztest
from statsmodels.stats.weightstats import ttest_ind

from app.modules.experiments import stats

rng = np.random.default_rng(1)


def agg(values: np.ndarray) -> stats.GroupStats:
    return stats.GroupStats(len(values), float(values.sum()), float((values**2).sum()))


def test_group_stats_match_numpy() -> None:
    v = rng.normal(5, 2, 1000)
    g = agg(v)
    assert g.mean == pytest.approx(v.mean())
    assert g.var == pytest.approx(v.var(ddof=1))
    assert stats.GroupStats(1, 3, 9).var == 0.0
    assert stats.GroupStats(0, 0, 0).mean == 0.0


def test_sample_size_binary_close_to_statsmodels() -> None:
    res = stats.sample_size("binary", 0.20, 0.10, daily_users=1000, traffic_share=0.5)
    es = proportion_effectsize(0.22, 0.20)
    ref = NormalIndPower().solve_power(es, alpha=0.05, power=0.8, ratio=1)
    assert abs(res.per_group - ref) / ref < 0.02  # arcsine vs normal approximation differ slightly
    assert res.total == 2 * res.per_group
    assert res.days == math.ceil(res.total / 500)


def test_sample_size_continuous_close_to_statsmodels() -> None:
    res = stats.sample_size("continuous", 10.0, 0.05, sd=8.0)
    ref = TTestIndPower().solve_power(0.5 / 8.0, alpha=0.05, power=0.8)
    assert abs(res.per_group - ref) / ref < 0.01
    assert res.days is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"metric_type": "binary", "baseline": 1.5, "mde_relative": 0.1},
        {"metric_type": "continuous", "baseline": 1.0, "mde_relative": 0.1},
        {"metric_type": "binary", "baseline": 0.1, "mde_relative": 0.0},
        {"metric_type": "binary", "baseline": 0.1, "mde_relative": 0.1, "alpha": 1.5},
    ],
)
def test_sample_size_validation(kwargs: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValueError):
        stats.sample_size(**kwargs)


def test_bayes_binary_matches_analytic_probability() -> None:
    a, b = stats.GroupStats(1000, 200, 200), stats.GroupStats(1000, 240, 240)
    res = stats.bayes_binary(a, b)
    # exact P(B>A) for Beta posteriors by numerical integration
    xs = np.linspace(0, 1, 20001)
    pdf_b = st.beta.pdf(xs, 241, 761)
    cdf_a = st.beta.cdf(xs, 201, 801)
    exact = np.trapezoid(pdf_b * cdf_a, xs)
    assert res.prob_b_better == pytest.approx(exact, abs=0.005)
    assert res.lift_ci[0] < res.lift_mean < res.lift_ci[1]
    assert res.lift_mean == pytest.approx(0.2, abs=0.02)
    assert res.posterior_a[0] == pytest.approx(201 / 1002, abs=0.002)
    assert 0 <= res.expected_loss_b < 0.01
    assert res.method == "beta-binomial"


def test_bayes_continuous_matches_normal_formula() -> None:
    va, vb = rng.normal(10, 3, 2000), rng.normal(10.2, 3, 2000)
    a, b = agg(va), agg(vb)
    res = stats.bayes_continuous(a, b)
    z = (b.mean - a.mean) / math.sqrt(a.var / a.n + b.var / b.n)
    assert res.prob_b_better == pytest.approx(st.norm.cdf(z), abs=0.005)
    with pytest.raises(ValueError):
        stats.bayes_continuous(stats.GroupStats(1, 1, 1), b)


def test_bootstrap_agrees_with_normal_on_large_samples() -> None:
    va, vb = rng.exponential(1.0, 3000), rng.exponential(1.08, 3000)
    boot = stats.bayes_bootstrap(va, vb)
    norm = stats.bayes_continuous(agg(va), agg(vb))
    assert boot.prob_b_better == pytest.approx(norm.prob_b_better, abs=0.03)
    with pytest.raises(ValueError):
        stats.bayes_bootstrap(np.array([1.0]), vb)


def test_z_test_matches_statsmodels() -> None:
    a, b = stats.GroupStats(5000, 1000, 1000), stats.GroupStats(5000, 1080, 1080)
    res = stats.z_test_proportions(a, b)
    z, p = proportions_ztest([1080, 1000], [5000, 5000])
    assert res.statistic == pytest.approx(z)
    assert res.p_value == pytest.approx(p)
    assert res.ci[0] < res.diff < res.ci[1]
    assert stats.z_test_proportions(stats.GroupStats(10, 0, 0), stats.GroupStats(10, 0, 0)).statistic == 0.0


def test_welch_matches_scipy_on_raw_data() -> None:
    va, vb = rng.normal(5, 2, 800), rng.normal(5.3, 3, 600)
    res = stats.welch_t_test(agg(va), agg(vb))
    ref = st.ttest_ind(vb, va, equal_var=False)
    assert res.statistic == pytest.approx(ref.statistic)
    assert res.p_value == pytest.approx(ref.pvalue)
    _, _, df = ttest_ind(vb, va, usevar="unequal")
    assert res.extra["df"] == pytest.approx(df)
    assert res.significant == (ref.pvalue < 0.05)


def test_cuped_reduces_variance_and_matches_manual_adjustment() -> None:
    n = 4000
    x = rng.normal(10, 3, 2 * n)
    y = 0.8 * x + rng.normal(0, 1, 2 * n)
    y[n:] += 0.1
    xa, xb, ya, yb = x[:n], x[n:], y[:n], y[n:]

    def c(xx: np.ndarray, yy: np.ndarray) -> stats.CupedStats:
        return stats.CupedStats(len(yy), yy.sum(), (yy**2).sum(), xx.sum(), (xx**2).sum(), (xx * yy).sum())

    res = stats.cuped(c(xa, ya), c(xb, yb))
    theta = np.cov(x, y, ddof=1)[0, 1] / x.var(ddof=1)
    adj_a, adj_b = ya - theta * (xa - x.mean()), yb - theta * (xb - x.mean())
    ref = st.ttest_ind(adj_b, adj_a, equal_var=False)
    assert res.extra["theta"] == pytest.approx(theta)
    assert res.statistic == pytest.approx(ref.statistic, rel=1e-6)
    assert res.extra["variance_reduction"] > 0.8
    assert res.significant


def test_srm_detects_mismatch_like_scipy() -> None:
    ok = stats.srm([5010, 4990], [0.5, 0.5])
    assert not ok.mismatch
    bad = stats.srm([5300, 4700], [0.5, 0.5])
    chi2, p = st.chisquare([5300, 4700], [5000, 5000])
    assert bad.mismatch
    assert bad.p_value == pytest.approx(p)
    assert bad.chi2 == pytest.approx(chi2)
    assert stats.srm([0, 0], [1, 1]).p_value == 1.0
    three = stats.srm([3300, 3350, 3350], [1, 1, 1])
    assert three.expected == pytest.approx([3333.33, 3333.33, 3333.33], abs=0.01)
