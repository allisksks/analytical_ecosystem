"""Statistical core of the A/B module (TZ 3.4). Works on aggregates only: n, sum, sum of squares per group
(and per-user values without identifiers for the bootstrap), so raw user rows never leave the source.

Bayesian (default): Beta-Binomial for binary metrics, normal approximation of the mean for continuous ones,
bootstrap as a distribution-free alternative. Frequentist (optional): two-proportion z-test, Welch t-test,
CUPED variance reduction. Sample ratio mismatch: chi-square goodness of fit.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from scipy import stats as st

MetricType = Literal["binary", "continuous"]
DRAWS = 200_000
SEED = 20260101


@dataclass(frozen=True)
class GroupStats:
    """Aggregates of one variant: users, sum of the metric and sum of squares (binary: sum = sumsq = conversions)."""

    n: int
    sum: float
    sumsq: float

    @property
    def mean(self) -> float:
        return self.sum / self.n if self.n else 0.0

    @property
    def var(self) -> float:
        """Unbiased sample variance from aggregates."""
        if self.n < 2:
            return 0.0
        return max((self.sumsq - self.sum**2 / self.n) / (self.n - 1), 0.0)


# ------------------------------------------------------------------ planning
@dataclass(frozen=True)
class SampleSize:
    per_group: int
    total: int
    days: int | None


def sample_size(
    metric_type: MetricType,
    baseline: float,
    mde_relative: float,
    *,
    sd: float | None = None,
    alpha: float = 0.05,
    power: float = 0.8,
    groups: int = 2,
    daily_users: float | None = None,
    traffic_share: float = 1.0,
) -> SampleSize:
    """Users per group for a two-sided test detecting a relative change ``mde_relative`` of ``baseline``."""
    if not 0 < mde_relative < 10:
        raise ValueError("mde_relative must be in (0, 10)")
    if not 0 < alpha < 1 or not 0 < power < 1:
        raise ValueError("alpha and power must be in (0, 1)")
    z_a = st.norm.ppf(1 - alpha / 2)
    z_b = st.norm.ppf(power)
    delta = baseline * mde_relative
    if metric_type == "binary":
        if not 0 < baseline < 1:
            raise ValueError("binary baseline must be a proportion in (0, 1)")
        p1, p2 = baseline, min(baseline + delta, 0.999999)
        p_bar = (p1 + p2) / 2
        n = (z_a * math.sqrt(2 * p_bar * (1 - p_bar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2 / (
            p2 - p1
        ) ** 2
    else:
        if sd is None or sd <= 0:
            raise ValueError("continuous metrics need a positive standard deviation")
        n = 2 * (z_a + z_b) ** 2 * sd**2 / delta**2
    per_group = math.ceil(n)
    total = per_group * groups
    days = math.ceil(total / (daily_users * traffic_share)) if daily_users else None
    return SampleSize(per_group, total, days)


# ------------------------------------------------------------------ bayesian
@dataclass
class BayesResult:
    prob_b_better: float
    lift_mean: float
    lift_ci: tuple[float, float]
    expected_loss_b: float  # expected relative loss if B is chosen and it is actually worse
    posterior_a: tuple[float, float] = (0.0, 0.0)  # (mean, sd) for plotting
    posterior_b: tuple[float, float] = (0.0, 0.0)
    method: str = ""


def _summarise(a: np.ndarray, b: np.ndarray, method: str) -> BayesResult:
    with np.errstate(divide="ignore", invalid="ignore"):
        lift = np.where(a != 0, b / a - 1, 0.0)
    lo, hi = np.percentile(lift, [2.5, 97.5])
    loss = np.maximum(a - b, 0) / np.where(np.abs(a) > 0, np.abs(a), 1)
    return BayesResult(
        prob_b_better=float(np.mean(b > a)),
        lift_mean=float(np.mean(lift)),
        lift_ci=(float(lo), float(hi)),
        expected_loss_b=float(np.mean(loss)),
        posterior_a=(float(np.mean(a)), float(np.std(a))),
        posterior_b=(float(np.mean(b)), float(np.std(b))),
        method=method,
    )


def bayes_binary(
    a: GroupStats, b: GroupStats, prior: tuple[float, float] = (1.0, 1.0), draws: int = DRAWS
) -> BayesResult:
    """Beta(prior) x Binomial: posterior Beta(alpha + x, beta + n - x) per group, P(B>A) by Monte Carlo."""
    rng = np.random.default_rng(SEED)
    pa = rng.beta(prior[0] + a.sum, prior[1] + a.n - a.sum, draws)
    pb = rng.beta(prior[0] + b.sum, prior[1] + b.n - b.sum, draws)
    return _summarise(pa, pb, "beta-binomial")


def bayes_continuous(a: GroupStats, b: GroupStats, draws: int = DRAWS) -> BayesResult:
    """Normal approximation of the posterior of the mean (flat prior): N(mean, var / n)."""
    if a.n < 2 or b.n < 2:
        raise ValueError("each group needs at least 2 users")
    rng = np.random.default_rng(SEED)
    ma = rng.normal(a.mean, math.sqrt(a.var / a.n), draws)
    mb = rng.normal(b.mean, math.sqrt(b.var / b.n), draws)
    return _summarise(ma, mb, "normal-approximation")


def bayes_bootstrap(values_a: np.ndarray, values_b: np.ndarray, iterations: int = 4000) -> BayesResult:
    """Bayesian bootstrap (Dirichlet weights) of the mean — robust to heavy tails such as ARPU."""
    if len(values_a) < 2 or len(values_b) < 2:
        raise ValueError("each group needs at least 2 users")
    rng = np.random.default_rng(SEED)
    wa = rng.dirichlet(np.ones(len(values_a)), iterations)
    wb = rng.dirichlet(np.ones(len(values_b)), iterations)
    return _summarise(wa @ values_a, wb @ values_b, "bayesian-bootstrap")


# ------------------------------------------------------------------ frequentist
@dataclass
class FrequentistResult:
    p_value: float
    statistic: float
    diff: float
    ci: tuple[float, float]
    method: str
    significant: bool = False
    extra: dict[str, float] = field(default_factory=dict)


def z_test_proportions(a: GroupStats, b: GroupStats, alpha: float = 0.05) -> FrequentistResult:
    pa, pb = a.mean, b.mean
    pooled = (a.sum + b.sum) / (a.n + b.n)
    se_pooled = math.sqrt(pooled * (1 - pooled) * (1 / a.n + 1 / b.n))
    z = (pb - pa) / se_pooled if se_pooled > 0 else 0.0
    p = 2 * (1 - st.norm.cdf(abs(z)))
    se = math.sqrt(pa * (1 - pa) / a.n + pb * (1 - pb) / b.n)
    q = st.norm.ppf(1 - alpha / 2)
    return FrequentistResult(
        float(p), float(z), pb - pa, (pb - pa - q * se, pb - pa + q * se), "two-proportion z-test", p < alpha
    )


def welch_t_test(a: GroupStats, b: GroupStats, alpha: float = 0.05) -> FrequentistResult:
    res = st.ttest_ind_from_stats(b.mean, math.sqrt(b.var), b.n, a.mean, math.sqrt(a.var), a.n, equal_var=False)
    va, vb = a.var / a.n, b.var / b.n
    df = (va + vb) ** 2 / (va**2 / (a.n - 1) + vb**2 / (b.n - 1)) if va + vb > 0 else float(a.n + b.n - 2)
    q = st.t.ppf(1 - alpha / 2, df)
    diff = b.mean - a.mean
    se = math.sqrt(va + vb)
    return FrequentistResult(
        float(res.pvalue),
        float(res.statistic),
        diff,
        (diff - q * se, diff + q * se),
        "welch t-test",
        bool(res.pvalue < alpha),
        {"df": df},
    )


@dataclass(frozen=True)
class CupedStats:
    """Aggregates for CUPED: metric y and pre-experiment covariate x per group."""

    n: int
    sum_y: float
    sum_y2: float
    sum_x: float
    sum_x2: float
    sum_xy: float


def cuped(a: CupedStats, b: CupedStats, alpha: float = 0.05) -> FrequentistResult:
    """CUPED (Deng et al., 2013): y' = y - theta (x - mean(x)), theta = cov(x, y) / var(x) over both groups."""
    n = a.n + b.n
    sx, sy = a.sum_x + b.sum_x, a.sum_y + b.sum_y
    cov = (a.sum_xy + b.sum_xy - sx * sy / n) / (n - 1)
    var_x = (a.sum_x2 + b.sum_x2 - sx**2 / n) / (n - 1)
    theta = cov / var_x if var_x > 0 else 0.0
    mean_x = sx / n

    def adjusted(g: CupedStats) -> GroupStats:
        # sums of y' and y'^2 expressed through the aggregates
        s = g.sum_y - theta * (g.sum_x - g.n * mean_x)
        ss = (
            g.sum_y2
            - 2 * theta * (g.sum_xy - mean_x * g.sum_y)
            + theta**2 * (g.sum_x2 - 2 * mean_x * g.sum_x + g.n * mean_x**2)
        )
        return GroupStats(g.n, s, ss)

    ga, gb = adjusted(a), adjusted(b)
    res = welch_t_test(ga, gb, alpha)
    raw_var = (GroupStats(a.n, a.sum_y, a.sum_y2).var / a.n) + (GroupStats(b.n, b.sum_y, b.sum_y2).var / b.n)
    adj_var = ga.var / ga.n + gb.var / gb.n
    res.method = "CUPED + welch t-test"
    res.extra.update({"theta": theta, "variance_reduction": 1 - adj_var / raw_var if raw_var else 0.0})
    return res


# ------------------------------------------------------------------ sample ratio mismatch
@dataclass
class SrmResult:
    p_value: float
    chi2: float
    expected: list[float]
    observed: list[int]
    mismatch: bool


def srm(observed: list[int], weights: list[float], threshold: float = 0.001) -> SrmResult:
    total = sum(observed)
    wsum = sum(weights)
    expected = [total * w / wsum for w in weights]
    if total == 0:
        return SrmResult(1.0, 0.0, expected, observed, False)
    chi2, p = st.chisquare(observed, expected)
    return SrmResult(float(p), float(chi2), expected, observed, bool(p < threshold))
