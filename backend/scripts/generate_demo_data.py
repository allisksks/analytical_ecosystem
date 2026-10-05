"""Demo data generator: a mobile-game portfolio with 3 months of events.

Produces Parquet files (one per table) that the DuckDB "files" connector reads directly,
and that can be loaded into ClickHouse/PostgreSQL for connector tests.

Tables follow the VKR data model: raw events, users, payments, ad revenue, A/B assignments
and four marts (mart_retention, mart_monetisation, mart_portfolio, mart_ua).

The data contains deliberate stories so every platform module has something to find:
* ``iron_shells`` runs the ``tutorial_v2`` experiment (B lifts retention ~+8%)
  and the ``starter_pack_price`` experiment ($4.99 -> $5.99, fewer payers but higher ARPU);
* after release 1.8.0 on iOS ``iap_purchase`` partly stops firing (an EMS alert story);
* acquisition sources differ in quality (organic retains best, mintegral worst).

Usage::

    uv run python -m scripts.generate_demo_data --out ./demo-data --scale 1.0
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa
from numpy.typing import NDArray

DAY = 86_400


@dataclass(frozen=True)
class AppProfile:
    app_id: str
    title: str
    users: int
    base_retention: float  # approx. D1
    decay: float  # power-law exponent of the retention curve
    payer_rate: float  # probability to pay on an active day
    ad_lambda: float  # mean ad impressions per active day
    sessions_mean: float
    has_matches: bool


APPS: tuple[AppProfile, ...] = (
    AppProfile("iron_shells", "Iron Shells", 14_000, 0.42, 0.52, 0.035, 2.5, 2.2, True),
    AppProfile("bloom_merge", "Bloom & Merge", 11_000, 0.38, 0.45, 0.022, 5.0, 2.8, False),
    AppProfile("drift_kings", "Drift Kings", 18_000, 0.30, 0.62, 0.006, 9.0, 1.6, False),
)

PLATFORMS = np.array(["android", "ios"])
PLATFORM_P = np.array([0.58, 0.42])
COUNTRIES = np.array(["US", "DE", "BR", "RU", "JP", "GB", "FR", "IN", "TR", "KZ"])
COUNTRY_P = np.array([0.22, 0.09, 0.12, 0.10, 0.06, 0.07, 0.06, 0.14, 0.08, 0.06])
COUNTRY_TIER = {
    "US": 1.0,
    "JP": 0.9,
    "GB": 0.85,
    "DE": 0.8,
    "FR": 0.7,
    "RU": 0.35,
    "KZ": 0.25,
    "TR": 0.25,
    "BR": 0.3,
    "IN": 0.15,
}
SOURCES = np.array(["organic", "facebook_int", "applovin_int", "mintegral_int", "tiktokglobal_int"])
SOURCE_P = np.array([0.38, 0.2, 0.17, 0.13, 0.12])
SOURCE_QUALITY = {
    "organic": 1.15,
    "facebook_int": 1.0,
    "applovin_int": 0.95,
    "mintegral_int": 0.78,
    "tiktokglobal_int": 0.88,
}
CPI = {"organic": 0.0, "facebook_int": 2.4, "applovin_int": 1.9, "mintegral_int": 1.1, "tiktokglobal_int": 1.5}
PRODUCTS = np.array(["gems_small", "starter_pack", "gems_medium", "battle_pass", "gems_large"])
PRODUCT_PRICE = np.array([0.99, 4.99, 9.99, 9.99, 49.99])
PRODUCT_P = np.array([0.42, 0.22, 0.18, 0.12, 0.06])
AD_NETWORKS = np.array(["applovin", "ironsource", "unity_ads", "mintegral"])
VERSIONS = (("1.6.0", 0), ("1.7.0", 31), ("1.8.0", 62))  # release day offsets
INCIDENT_VERSION = "1.8.0"


def _version_at(day_idx: NDArray[np.int64]) -> NDArray[np.str_]:
    out = np.full(day_idx.shape, VERSIONS[0][0], dtype=object)
    for name, offset in VERSIONS[1:]:
        out[day_idx >= offset] = name
    return out.astype(str)


def _choice(rng: np.random.Generator, values: NDArray[np.str_], p: NDArray[np.float64], n: int) -> NDArray[np.str_]:
    return values[rng.choice(len(values), size=n, p=p / p.sum())]


def generate_app(app: AppProfile, start: date, days: int, scale: float, rng: np.random.Generator) -> dict[str, dict]:
    n = max(200, int(app.users * scale))
    start_ts = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())

    # --- installs: growth + weekly seasonality ---
    day_axis = np.arange(days)
    weights = (1 + day_axis / days) * (1 + 0.15 * np.isin(day_axis % 7, [5, 6]))
    install_day = np.sort(rng.choice(days, size=n, p=weights / weights.sum()))
    install_ts = start_ts + install_day * DAY + rng.integers(0, DAY, n)
    user_id = np.array([f"{app.app_id[:2]}_{i:07d}" for i in range(n)])
    device_id = np.array([f"dev_{h:016x}" for h in rng.integers(0, 2**62, n)])
    platform = _choice(rng, PLATFORMS, PLATFORM_P, n)
    country = _choice(rng, COUNTRIES, COUNTRY_P, n)
    source = _choice(rng, SOURCES, SOURCE_P, n)
    campaign = np.where(
        source == "organic",
        "",
        np.char.add(np.char.add(source.astype(str), "_"), rng.choice(["broad", "lookalike", "retarget"], n)),
    )
    install_version = _version_at(install_day)

    # --- experiments (iron_shells only) ---
    tutorial_variant = np.full(n, "", dtype=object)
    price_variant = np.full(n, "", dtype=object)
    if app.app_id == "iron_shells":
        in_tut = (install_day >= 40) & (install_day < 68)
        tutorial_variant[in_tut] = np.where(rng.random(in_tut.sum()) < 0.5, "A", "B")
        in_price = (install_day >= 20) & (install_day < 50)
        price_variant[in_price] = np.where(rng.random(in_price.sum()) < 0.5, "A", "B")

    # --- engagement & retention ---
    quality = np.vectorize(SOURCE_QUALITY.get)(source).astype(float)
    engagement = rng.lognormal(mean=0.0, sigma=0.55, size=n) * quality
    engagement *= np.where(tutorial_variant == "B", 1.09, 1.0)
    remaining = days - install_day  # days observable incl. install day

    max_n = days
    dn = np.arange(max_n)
    base_curve = np.where(dn == 0, 1.0, app.base_retention * np.power(np.maximum(dn, 1), -app.decay))
    probs = np.clip(np.outer(engagement, base_curve), 0, 0.97)
    probs[:, 0] = 1.0
    active = rng.random((n, max_n)) < probs
    active &= dn[None, :] < remaining[:, None]
    u_idx, day_n = np.nonzero(active)
    act_day = install_day[u_idx] + day_n
    act_version = _version_at(act_day)
    # users update the app: activity version is max(install version, release at that day)
    # dates travel as datetime64[s] (DuckDB cannot ingest datetime64[D]) and are cast to DATE later
    install_date_arr = (np.datetime64(start) + np.arange(days)).astype("datetime64[s]")
    act_date = install_date_arr[act_day]

    users = {
        "app_id": np.full(n, app.app_id),
        "user_id": user_id,
        "device_id": device_id,
        "install_date": install_date_arr[install_day],
        "install_ts": install_ts.astype("datetime64[s]"),
        "platform": platform,
        "country": country,
        "source": source,
        "campaign": campaign.astype(str),
        "app_version": install_version,
    }
    mart_retention = {
        "app_id": np.full(len(u_idx), app.app_id),
        "user_id": user_id[u_idx],
        "install_date": install_date_arr[install_day[u_idx]],
        "activity_date": act_date,
        "day_n": day_n.astype(np.int32),
        "platform": platform[u_idx],
        "country": country[u_idx],
        "source": source[u_idx],
        "app_version": act_version,
    }

    # --- sessions ---
    m = len(u_idx)
    sessions = 1 + rng.poisson(app.sessions_mean - 1, m)
    s_user = np.repeat(u_idx, sessions)
    s_day = np.repeat(act_day, sessions)
    s_dn = np.repeat(day_n, sessions)
    s_ver = np.repeat(act_version, sessions)
    s_ts = start_ts + s_day * DAY + rng.integers(6 * 3600, DAY, len(s_user))
    s_id = np.array([f"s_{h:012x}" for h in rng.integers(0, 2**46, len(s_user))])

    ev: dict[str, list[NDArray]] = {k: [] for k in ("ts", "name", "user", "session", "ver", "params")}

    def emit(ts: NDArray, name: str | NDArray, uidx: NDArray, sess: NDArray, ver: NDArray, params: NDArray) -> None:
        ev["ts"].append(ts)
        ev["name"].append(np.full(len(ts), name) if isinstance(name, str) else name)
        ev["user"].append(uidx)
        ev["session"].append(sess)
        ev["ver"].append(ver)
        ev["params"].append(params)

    emit(s_ts, "session_start", s_user, s_id, s_ver, np.full(len(s_ts), "{}"))

    # tutorial funnel on install day
    first = s_dn == 0
    fu, fts, fs, fv = s_user[first], s_ts[first], s_id[first], s_ver[first]
    _, first_idx = np.unique(fu, return_index=True)
    fu, fts, fs, fv = fu[first_idx], fts[first_idx], fs[first_idx], fv[first_idx]
    step_survival = np.array([1, 0.97, 0.95, 0.83, 0.81, 0.8, 0.71, 0.7, 0.69, 0.68])
    reach = rng.random(len(fu))
    for step, surv in enumerate(step_survival, start=1):
        ok = reach < surv * np.minimum(1.0, engagement[fu] * 1.1)
        ok |= step == 1
        emit(
            fts[ok] + step * 20, "tutorial_step", fu[ok], fs[ok], fv[ok], np.full(ok.sum(), json.dumps({"step": step}))
        )

    # core loop events
    levels = rng.poisson(2.5, len(s_user))
    l_user = np.repeat(s_user, levels)
    l_ts = np.repeat(s_ts, levels) + rng.integers(30, 1800, levels.sum())
    l_s, l_v = np.repeat(s_id, levels), np.repeat(s_ver, levels)
    lvl = np.minimum(1 + np.repeat(s_dn, levels) * 2 + rng.integers(0, 3, levels.sum()), 200)
    lp = np.char.add(np.char.add('{"level": ', lvl.astype(str)), "}")
    emit(l_ts, "level_start", l_user, l_s, l_v, lp)
    win = rng.random(len(l_user)) < 0.72
    emit(l_ts[win] + 90, "level_complete", l_user[win], l_s[win], l_v[win], lp[win])
    if app.has_matches:
        mode = rng.choice(["pve", "pvp"], len(l_user), p=[0.6, 0.4])
        emit(l_ts + 5, "match_start", l_user, l_s, l_v, np.char.add(np.char.add('{"mode": "', mode), '"}'))
        chest = rng.random(len(l_user)) < 0.35
        emit(
            l_ts[chest] + 120,
            "chest_open",
            l_user[chest],
            l_s[chest],
            l_v[chest],
            np.full(chest.sum(), '{"chest": "silver"}'),
        )

    # payments
    pay_rate = app.payer_rate * np.minimum(engagement[u_idx], 3) * np.vectorize(COUNTRY_TIER.get)(country[u_idx])
    pay_rate = np.where(price_variant[u_idx] == "B", pay_rate * 0.88, pay_rate)
    pays = rng.random(m) < pay_rate
    p_user, p_day, p_ver = u_idx[pays], act_day[pays], act_version[pays]
    prod_idx = rng.choice(len(PRODUCTS), size=len(p_user), p=PRODUCT_P)
    price = PRODUCT_PRICE[prod_idx].copy()
    is_starter_b = (PRODUCTS[prod_idx] == "starter_pack") & (price_variant[p_user] == "B")
    price[is_starter_b] = 5.99
    p_ts = start_ts + p_day * DAY + rng.integers(8 * 3600, DAY, len(p_user))
    p_sess = np.array([f"s_{h:012x}" for h in rng.integers(0, 2**46, len(p_user))])
    payments = {
        "app_id": np.full(len(p_user), app.app_id),
        "user_id": user_id[p_user],
        "event_ts": p_ts.astype("datetime64[s]"),
        "event_date": install_date_arr[p_day],
        "product_id": PRODUCTS[prod_idx],
        "revenue_usd": np.round(price * 0.7, 2),  # net of store fee
        "platform": platform[p_user],
        "country": country[p_user],
        "app_version": p_ver,
    }
    # EMS incident: on iOS 1.8.0 most iap_purchase events stop firing (payments are still in the store report)
    logged = ~((platform[p_user] == "ios") & (p_ver == INCIDENT_VERSION) & (rng.random(len(p_user)) < 0.85))
    pp = np.array(
        [
            json.dumps({"product_id": pr, "price_usd": float(pc), "currency": "USD"})
            for pr, pc in zip(PRODUCTS[prod_idx], price, strict=True)
        ]
    )
    emit(p_ts[logged], "iap_purchase", p_user[logged], p_sess[logged], p_ver[logged], pp[logged])

    # ads
    imps = rng.poisson(app.ad_lambda * np.minimum(engagement[u_idx], 2.5), m)
    has_ads = imps > 0
    tier = np.vectorize(COUNTRY_TIER.get)(country[u_idx[has_ads]])
    ecpm = rng.gamma(4.0, 4.0, has_ads.sum()) * tier
    ad_rev = {
        "app_id": np.full(has_ads.sum(), app.app_id),
        "user_id": user_id[u_idx[has_ads]],
        "event_date": act_date[has_ads],
        "network": rng.choice(AD_NETWORKS, has_ads.sum()),
        "impressions": imps[has_ads].astype(np.int32),
        "revenue_usd": np.round(imps[has_ads] * ecpm / 1000, 5),
        "platform": platform[u_idx[has_ads]],
        "country": country[u_idx[has_ads]],
    }
    a_ts = start_ts + act_day[has_ads] * DAY + rng.integers(0, DAY, has_ads.sum())
    emit(
        a_ts,
        "ad_impression",
        u_idx[has_ads],
        np.full(has_ads.sum(), ""),
        act_version[has_ads],
        np.char.add(np.char.add('{"count": ', imps[has_ads].astype(str)), "}"),
    )

    # assemble events
    e_user = np.concatenate(ev["user"])
    e_ts = np.concatenate(ev["ts"])
    order = np.argsort(e_ts, kind="stable")
    e_user, e_ts = e_user[order], e_ts[order]
    events = {
        "app_id": np.full(len(e_ts), app.app_id),
        "event_ts": e_ts.astype("datetime64[s]"),
        "event_date": e_ts.astype("datetime64[s]").astype("datetime64[D]").astype("datetime64[s]"),
        "event_name": np.concatenate(ev["name"])[order],
        "user_id": user_id[e_user],
        "device_id": device_id[e_user],
        "session_id": np.concatenate(ev["session"])[order],
        "platform": platform[e_user],
        "country": country[e_user],
        "source": source[e_user],
        "app_version": np.concatenate(ev["ver"])[order],
        "params": np.concatenate(ev["params"])[order],
    }

    ab_rows_u, ab_rows_k, ab_rows_v = [], [], []
    for key, arr in (("tutorial_v2", tutorial_variant), ("starter_pack_price", price_variant)):
        mask = arr != ""
        ab_rows_u.append(np.nonzero(mask)[0])
        ab_rows_k.append(np.full(mask.sum(), key))
        ab_rows_v.append(arr[mask].astype(str))
    ab_u = np.concatenate(ab_rows_u)
    ab = {
        "app_id": np.full(len(ab_u), app.app_id),
        "experiment_key": np.concatenate(ab_rows_k),
        "user_id": user_id[ab_u],
        "variant": np.concatenate(ab_rows_v),
        "assigned_at": install_ts[ab_u].astype("datetime64[s]"),
        "platform": platform[ab_u],
        "country": country[ab_u],
        "source": source[ab_u],
    }

    ua_cost = np.vectorize(CPI.get)(source) * (0.6 + np.vectorize(COUNTRY_TIER.get)(country))
    users["cpi_usd"] = np.round(ua_cost, 3)
    return {
        "users": users,
        "mart_retention": mart_retention,
        "events": events,
        "payments": payments,
        "ad_revenue": ad_rev,
        "ab_assignments": ab,
    }


MART_SQL = {
    "mart_monetisation": """
        WITH dau AS (
            SELECT app_id, activity_date AS event_date, platform, country, source, count(*) AS dau
            FROM mart_retention GROUP BY ALL
        ), iap AS (
            SELECT p.app_id, p.event_date, p.platform, p.country, u.source,
                   count(DISTINCT p.user_id) AS payers, sum(p.revenue_usd) AS iap_revenue
            FROM payments p JOIN users u USING (app_id, user_id) GROUP BY ALL
        ), ads AS (
            SELECT a.app_id, a.event_date, a.platform, a.country, u.source, sum(a.revenue_usd) AS ad_revenue
            FROM ad_revenue a JOIN users u USING (app_id, user_id) GROUP BY ALL
        )
        SELECT d.app_id, d.event_date, d.platform, d.country, d.source, d.dau,
               coalesce(i.payers, 0) AS payers,
               round(coalesce(i.iap_revenue, 0), 2) AS iap_revenue,
               round(coalesce(a.ad_revenue, 0), 2) AS ad_revenue,
               round(coalesce(i.iap_revenue, 0) + coalesce(a.ad_revenue, 0), 2) AS revenue
        FROM dau d
        LEFT JOIN iap i USING (app_id, event_date, platform, country, source)
        LEFT JOIN ads a USING (app_id, event_date, platform, country, source)
        ORDER BY 1, 2
    """,
    "mart_portfolio": """
        WITH daily AS (
            SELECT app_id, event_date, sum(dau) AS dau, sum(revenue) AS revenue FROM mart_monetisation GROUP BY ALL
        ), installs AS (
            SELECT app_id, install_date AS event_date, count(*) AS installs FROM users GROUP BY ALL
        ), ret AS (
            SELECT app_id, install_date AS event_date,
                   count(DISTINCT CASE WHEN day_n = 1 THEN user_id END) / count(DISTINCT user_id) AS d1_retention,
                   count(DISTINCT CASE WHEN day_n = 7 THEN user_id END) / count(DISTINCT user_id) AS d7_retention
            FROM mart_retention GROUP BY ALL
        )
        SELECT d.app_id, d.event_date, d.dau, coalesce(i.installs, 0) AS installs, round(d.revenue, 2) AS revenue,
               round(r.d1_retention, 4) AS d1_retention, round(r.d7_retention, 4) AS d7_retention
        FROM daily d LEFT JOIN installs i USING (app_id, event_date) LEFT JOIN ret r USING (app_id, event_date)
        ORDER BY 1, 2
    """,
    "mart_ua": """
        WITH rev AS (
            SELECT u.app_id, u.user_id, sum(p.revenue_usd) AS rev
            FROM users u JOIN payments p USING (app_id, user_id)
            WHERE p.event_date < u.install_date + INTERVAL 7 DAY GROUP BY ALL
        ), ad AS (
            SELECT u.app_id, u.user_id, sum(a.revenue_usd) AS rev
            FROM users u JOIN ad_revenue a USING (app_id, user_id)
            WHERE a.event_date < u.install_date + INTERVAL 7 DAY GROUP BY ALL
        )
        SELECT u.app_id, u.install_date, u.source, u.campaign, u.country, count(*) AS installs,
               round(sum(u.cpi_usd), 2) AS spend_usd,
               round(sum(coalesce(r.rev, 0) + coalesce(a.rev, 0)), 2) AS revenue_d7_usd
        FROM users u LEFT JOIN rev r USING (app_id, user_id) LEFT JOIN ad a USING (app_id, user_id)
        GROUP BY ALL ORDER BY 1, 2
    """,
}


def generate(out: Path, scale: float = 1.0, days: int = 91, end: date | None = None, seed: int = 42) -> dict[str, int]:
    rng = np.random.default_rng(seed)
    end = end or datetime.now(UTC).date()
    start = end - timedelta(days=days - 1)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    counts: dict[str, int] = {}
    per_table: dict[str, list[str]] = {}
    for app in APPS:
        tables = generate_app(app, start, days, scale, rng)
        for name, cols in tables.items():
            view = f"{name}__{app.app_id}"
            con.register(view, pa.table({k: pa.array(np.asarray(v)) for k, v in cols.items()}))
            per_table.setdefault(name, []).append(view)
    for name, views in per_table.items():
        con.execute(f"CREATE TABLE {name} AS " + " UNION ALL BY NAME ".join(f"SELECT * FROM {v}" for v in views))
        for (col,) in con.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = ? AND column_name LIKE '%_date'",
            [name],
        ).fetchall():
            con.execute(f"ALTER TABLE {name} ALTER {col} TYPE DATE")
    for name, sql in MART_SQL.items():
        con.execute(f"CREATE TABLE {name} AS {sql}")
    for name in [*per_table, *MART_SQL]:
        path = out / f"{name}.parquet"
        con.execute(f"COPY {name} TO '{path}' (FORMAT parquet, COMPRESSION zstd)")
        row = con.execute(f"SELECT count(*) FROM {name}").fetchone()
        counts[name] = int(row[0]) if row else 0
    (out / "_manifest.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "start": str(start),
                "end": str(end),
                "scale": scale,
                "seed": seed,
                "apps": [a.app_id for a in APPS],
                "rows": counts,
            },
            indent=2,
        )
    )
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("./demo-data"))
    parser.add_argument("--scale", type=float, default=1.0, help="multiplier for number of users")
    parser.add_argument("--days", type=int, default=91)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--end", type=date.fromisoformat, default=None, help="last day (default: today)")
    args = parser.parse_args()
    t0 = time.perf_counter()
    counts = generate(args.out, args.scale, args.days, args.end, args.seed)
    for name, rows in counts.items():
        print(f"{name:20s} {rows:>12,d}")
    print(f"done in {time.perf_counter() - t0:.1f}s -> {args.out.resolve()}")


if __name__ == "__main__":
    main()
