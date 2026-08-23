"""
IntelliFlow — Shared Feature Engineering Module
================================================
SINGLE SOURCE OF TRUTH for feature computation.

Both the training notebook AND the Django serving layer import this file.
Never duplicate this logic anywhere else — that is how train/serve skew happens.

Usage (training):
    X, encoders = build_features(df, fit=True)

Usage (serving / Django):
    row = build_inference_row(history_df, target_date, area, road,
                              weather_forecast, roadwork_planned, encoders)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.preprocessing import LabelEncoder

# --------------------------------------------------------------------------
# CONTRACT CONSTANTS — Django reads these too
# --------------------------------------------------------------------------
FEATURE_VERSION = "1.0.0"

CONGESTION_BINS = [-np.inf, 40.0, 65.0, 85.0, np.inf]
CONGESTION_LABELS = ["low", "moderate", "high", "severe"]

GREEN_TIME_MAP = {"low": 30, "moderate": 45, "high": 60, "severe": 75}
GREEN_TIME_MIN, GREEN_TIME_MAX = 20, 90

LAG_DAYS = [1, 2, 3, 7, 14]
ROLL_WINDOWS = [3, 7, 14]
WARMUP_DAYS = 14          # rows lost per intersection to lag warmup
MIN_HISTORY_DAYS = 21     # Django must supply at least this much history

RAW_COLUMNS = [
    "Date", "Area Name", "Road/Intersection Name", "Traffic Volume",
    "Average Speed", "Travel Time Index", "Congestion Level",
    "Road Capacity Utilization", "Incident Reports", "Environmental Impact",
    "Public Transport Usage", "Traffic Signal Compliance", "Parking Usage",
    "Pedestrian and Cyclist Count", "Weather Conditions",
    "Roadwork and Construction Activity",
]

# Columns that describe day t+1 and MUST NEVER be used un-lagged as features.
LEAKY_COLUMNS = [
    "Traffic Volume", "Average Speed", "Travel Time Index",
    "Congestion Level", "Road Capacity Utilization", "Environmental Impact",
]

ADVERSE_WEATHER = {"Rain", "Fog"}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def make_intersection_id(area: str, road: str) -> str:
    """Composite key used everywhere, including Django's Intersection model."""
    return f"{str(area).strip()}::{str(road).strip()}"


def classify_congestion(level: float) -> str:
    """Map a raw 0-100 congestion score to its class label."""
    if level is None or (isinstance(level, float) and np.isnan(level)):
        return CONGESTION_LABELS[0]
    for upper, label in zip(CONGESTION_BINS[1:], CONGESTION_LABELS):
        if level < upper:
            return label
    return CONGESTION_LABELS[-1]


def recommend_green_seconds(congestion_class: str, num_approaches: int = 4) -> int:
    """Decision-support only. No physical signal hardware is driven."""
    base = GREEN_TIME_MAP.get(congestion_class, 45)
    adj = base * (1 + 0.05 * (num_approaches - 4))
    return int(np.clip(round(adj), GREEN_TIME_MIN, GREEN_TIME_MAX))


def _india_holidays(years):
    """Karnataka holiday calendar. Degrades to empty set if lib missing."""
    try:
        import holidays as _h
        return _h.India(subdiv="KA", years=list(years))
    except Exception:
        return {}


def _slope(series: pd.Series) -> float:
    """Least-squares slope of a short window — congestion momentum."""
    y = series.to_numpy(dtype=float)
    if len(y) < 2 or np.isnan(y).any():
        return 0.0
    x = np.arange(len(y), dtype=float)
    return float(np.polyfit(x, y, 1)[0])


# --------------------------------------------------------------------------
# Normalisation: raw CSV -> canonical long frame
# --------------------------------------------------------------------------
def normalize_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Rename to snake_case, build intersection_id, sort, dedupe."""
    d = df.copy()
    d["Date"] = pd.to_datetime(d["Date"])
    d = d.rename(columns={
        "Date": "date",
        "Area Name": "area",
        "Road/Intersection Name": "road",
        "Traffic Volume": "volume",
        "Average Speed": "speed",
        "Travel Time Index": "tti",
        "Congestion Level": "congestion",
        "Road Capacity Utilization": "capacity_util",
        "Incident Reports": "incidents",
        "Environmental Impact": "env_impact",
        "Public Transport Usage": "pt_usage",
        "Traffic Signal Compliance": "signal_compliance",
        "Parking Usage": "parking_usage",
        "Pedestrian and Cyclist Count": "ped_count",
        "Weather Conditions": "weather",
        "Roadwork and Construction Activity": "roadwork",
    })
    d["intersection_id"] = [make_intersection_id(a, r)
                            for a, r in zip(d["area"], d["road"])]
    d["roadwork_flag"] = (d["roadwork"].astype(str).str.strip()
                          .str.lower().eq("yes").astype(int))
    d = (d.drop_duplicates(subset=["intersection_id", "date"], keep="last")
           .sort_values(["intersection_id", "date"])
           .reset_index(drop=True))
    return d


def reindex_continuous(d: pd.DataFrame, verbose: bool = True) -> pd.DataFrame:
    """
    Force a continuous daily index per intersection so lag features are
    genuinely 'N days ago' and not 'N rows ago'. Synthesized rows are flagged.
    """
    numeric = ["volume", "speed", "tti", "congestion", "capacity_util",
               "incidents", "env_impact", "pt_usage", "signal_compliance",
               "parking_usage", "ped_count", "roadwork_flag"]
    out = []
    synthesized = 0
    for iid, g in d.groupby("intersection_id", sort=False):
        g = g.set_index("date").sort_index()
        full = pd.date_range(g.index.min(), g.index.max(), freq="D")
        missing = len(full) - len(g)
        synthesized += missing
        g = g.reindex(full)
        g.index.name = "date"
        g["is_synthetic"] = g["volume"].isna().astype(int)
        g[numeric] = g[numeric].interpolate(method="linear", limit_direction="both")
        for c in ["area", "road", "intersection_id", "weather", "roadwork"]:
            g[c] = g[c].ffill().bfill()
        g["intersection_id"] = iid
        out.append(g.reset_index())
    res = pd.concat(out, ignore_index=True).sort_values(
        ["intersection_id", "date"]).reset_index(drop=True)
    res["roadwork_flag"] = res["roadwork_flag"].round().astype(int)
    if verbose:
        print(f"   reindex_continuous: {synthesized} synthetic rows inserted "
              f"({synthesized / max(len(res), 1):.2%} of final)")
    return res


# --------------------------------------------------------------------------
# THE feature builder
# --------------------------------------------------------------------------
def build_features(
    df: pd.DataFrame,
    encoders: dict | None = None,
    fit: bool = False,
    profile_source: pd.DataFrame | None = None,
    dropna: bool = True,
    verbose: bool = True,
) -> tuple[pd.DataFrame, dict]:
    """
    Build the model-ready frame.

    Target convention
    -----------------
    Every row describes a PREDICTION FOR DAY t+1.
      * `target_volume` / `target_congestion` / `target_class` come from day t+1
      * every feature is derived from day <= t, EXCEPT calendar features and
        weather/roadwork for t+1, which are legitimately known in advance
        (weather = forecast, roadwork = scheduled).

    Parameters
    ----------
    fit : True during training (fits encoders + intersection profiles),
          False at serve time (reuses supplied encoders).
    profile_source : frame used to compute static per-intersection profile stats.
          Pass the TRAIN SPLIT ONLY during training to avoid leakage.
    """
    d = df.copy()
    if "intersection_id" not in d.columns:
        d = normalize_raw(d)
    d = d.sort_values(["intersection_id", "date"]).reset_index(drop=True)

    if encoders is None:
        encoders = {}
    g = d.groupby("intersection_id", sort=False)

    F = pd.DataFrame(index=d.index)
    F["intersection_id"] = d["intersection_id"]
    F["date"] = d["date"]                      # date of day t (feature date)

    # ---------------- TARGETS (day t+1) ----------------
    F["target_date"] = g["date"].shift(-1)
    F["target_volume"] = g["volume"].shift(-1)
    F["target_congestion"] = g["congestion"].shift(-1)

    # ---------------- Known-in-advance context for t+1 ----------------
    nxt_weather = g["weather"].shift(-1)
    nxt_roadwork = g["roadwork_flag"].shift(-1)

    # ---------------- TEMPORAL (of target day t+1) ----------------
    td = pd.to_datetime(F["target_date"])
    F["day_of_week"] = td.dt.dayofweek
    F["day_of_month"] = td.dt.day
    F["month"] = td.dt.month
    F["quarter"] = td.dt.quarter
    F["week_of_year"] = td.dt.isocalendar().week.astype("float")
    F["is_weekend"] = (td.dt.dayofweek >= 5).astype("float")
    F["is_month_start"] = td.dt.is_month_start.astype("float")
    F["is_month_end"] = td.dt.is_month_end.astype("float")

    yrs = td.dropna().dt.year.unique()
    hol = _india_holidays(yrs)
    F["is_indian_holiday"] = td.map(
        lambda x: 1.0 if (pd.notna(x) and x.date() in hol) else 0.0)

    F["dow_sin"] = np.sin(2 * np.pi * F["day_of_week"] / 7)
    F["dow_cos"] = np.cos(2 * np.pi * F["day_of_week"] / 7)
    F["month_sin"] = np.sin(2 * np.pi * F["month"] / 12)
    F["month_cos"] = np.cos(2 * np.pi * F["month"] / 12)
    F["doy_sin"] = np.sin(2 * np.pi * td.dt.dayofyear / 365.25)
    F["doy_cos"] = np.cos(2 * np.pi * td.dt.dayofyear / 365.25)

    # ---------------- LAGS (day t is lag_1 relative to target t+1) ----------
    lag_spec = {
        "volume": [1, 2, 3, 7, 14],
        "congestion": [1, 2, 3, 7],
        "speed": [1, 3, 7],
        "tti": [1, 7],
        "capacity_util": [1, 7],
        "incidents": [1, 7],
        "env_impact": [1, 7],
    }
    for col, lags in lag_spec.items():
        for L in lags:
            F[f"{col}_lag_{L}"] = g[col].shift(L - 1)

    for col in ["pt_usage", "parking_usage", "signal_compliance"]:
        F[f"{col}_lag_1"] = g[col].shift(0)
    F["ped_count_lag_7"] = g["ped_count"].shift(6)

    # ---------------- ROLLING (windows END at day t) ----------------
    for w in ROLL_WINDOWS:
        F[f"volume_roll_mean_{w}"] = g["volume"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).mean())
        F[f"volume_roll_std_{w}"] = g["volume"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).std())
        F[f"volume_roll_max_{w}"] = g["volume"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).max())
        F[f"congestion_roll_mean_{w}"] = g["congestion"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).mean())
        F[f"congestion_roll_std_{w}"] = g["congestion"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).std())
        F[f"speed_roll_mean_{w}"] = g["speed"].transform(
            lambda s, w=w: s.rolling(w, min_periods=w).mean())

    # ---------------- DELTA / MOMENTUM ----------------
    F["volume_diff_1"] = F["volume_lag_1"] - F["volume_lag_2"]
    F["volume_diff_7"] = F["volume_lag_1"] - F["volume_lag_7"]
    F["volume_pct_change"] = F["volume_diff_1"] / (F["volume_lag_2"].abs() + 1)
    F["congestion_diff_1"] = F["congestion_lag_1"] - F["congestion_lag_2"]
    F["congestion_diff_7"] = F["congestion_lag_1"] - F["congestion_lag_7"]
    F["congestion_trend_7"] = g["congestion"].transform(
        lambda s: s.rolling(7, min_periods=7).apply(_slope, raw=False))
    F["volume_vs_roll7"] = F["volume_lag_1"] / (F["volume_roll_mean_7"] + 1)
    F["congestion_vs_roll7"] = F["congestion_lag_1"] - F["congestion_roll_mean_7"]
    F["congestion_saturated_lag_1"] = (F["congestion_lag_1"] >= 99.5).astype("float")
    F["congestion_saturated_streak_7"] = g["congestion"].transform(
        lambda s: s.ge(99.5).rolling(7, min_periods=7).sum())

    # ---------------- SPATIAL / NEIGHBOUR ----------------
    d_tmp = d[["date", "area", "intersection_id", "congestion", "volume"]].copy()
    area_daily = (d_tmp.groupby(["area", "date"], as_index=False)
                  .agg(area_cong=("congestion", "mean"),
                       area_vol=("volume", "mean"),
                       area_n=("congestion", "size")))
    d_tmp = d_tmp.merge(area_daily, on=["area", "date"], how="left")
    # leave-one-out so an intersection never sees its own same-day value
    denom = (d_tmp["area_n"] - 1).replace(0, np.nan)
    d_tmp["peer_cong"] = ((d_tmp["area_cong"] * d_tmp["area_n"]
                           - d_tmp["congestion"]) / denom)
    d_tmp["peer_cong"] = d_tmp["peer_cong"].fillna(d_tmp["area_cong"])
    F["area_peer_congestion_lag_1"] = (
        d_tmp.groupby("intersection_id")["peer_cong"].shift(0).to_numpy())
    F["area_peer_congestion_roll_7"] = (
        d_tmp.groupby("intersection_id")["peer_cong"]
        .transform(lambda s: s.rolling(7, min_periods=7).mean()).to_numpy())

    city_daily = (d_tmp.groupby("date", as_index=False)
                  .agg(city_cong=("congestion", "mean")))
    city_map = dict(zip(city_daily["date"], city_daily["city_cong"]))
    F["city_congestion_lag_1"] = d["date"].map(city_map)

    # ---------------- CATEGORICAL ENCODING ----------------
    def _enc(name, values, classes_hint=None):
        vals = pd.Series(values).astype(str).fillna("UNK")
        if fit:
            le = LabelEncoder()
            uniq = sorted(set(vals) | {"UNK"})
            le.fit(uniq)
            encoders[name] = le
        le = encoders.get(name)
        if le is None:
            raise KeyError(f"Encoder '{name}' missing. Train with fit=True first.")
        known = set(le.classes_)
        vals = vals.where(vals.isin(known), "UNK")
        return le.transform(vals).astype(float)

    F["area_encoded"] = _enc("area", d["area"])
    F["intersection_encoded"] = _enc("intersection", d["intersection_id"])
    F["weather_encoded"] = _enc("weather", nxt_weather.fillna("Clear"))
    F["is_adverse_weather"] = nxt_weather.isin(ADVERSE_WEATHER).astype(float)
    F["weather_encoded_lag_1"] = _enc("weather", d["weather"])
    F["roadwork_flag"] = nxt_roadwork.astype(float)
    F["roadwork_flag_lag_1"] = d["roadwork_flag"].astype(float)

    # ---------------- STATIC INTERSECTION PROFILE ----------------
    src = profile_source if profile_source is not None else d
    if fit or "intersection_profile" not in encoders:
        prof = (src.groupby("intersection_id")
                .agg(hist_mean_volume=("volume", "mean"),
                     hist_std_volume=("volume", "std"),
                     hist_mean_congestion=("congestion", "mean"),
                     hist_mean_speed=("speed", "mean"),
                     hist_severe_rate=("congestion", lambda s: (s >= 85).mean()))
                .fillna(0.0))
        encoders["intersection_profile"] = prof
    prof = encoders["intersection_profile"]
    glob = prof.mean(numeric_only=True)
    for c in prof.columns:
        F[f"prof_{c}"] = d["intersection_id"].map(prof[c]).fillna(glob[c]).astype(float)
    F["volume_vs_profile"] = F["volume_lag_1"] / (F["prof_hist_mean_volume"] + 1)

    # ---------------- FINALISE ----------------
    F["target_class"] = F["target_congestion"].map(
        lambda v: classify_congestion(v) if pd.notna(v) else np.nan)

    meta_cols = ["intersection_id", "date", "target_date",
                 "target_volume", "target_congestion", "target_class"]
    feat_cols = [c for c in F.columns if c not in meta_cols]

    if dropna:
        before = len(F)
        F = F.dropna(subset=feat_cols + ["target_volume", "target_class"]).reset_index(drop=True)
        if verbose:
            print(f"   build_features: {before} -> {len(F)} rows "
                  f"({before - len(F)} dropped to lag warmup / final row)")

    F[feat_cols] = F[feat_cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    encoders["feature_columns"] = feat_cols
    encoders["feature_version"] = FEATURE_VERSION

    assert_no_leakage(feat_cols, verbose=verbose)
    return F, encoders


def assert_no_leakage(feature_cols, verbose: bool = True) -> None:
    """Fail loudly if any same-day target measurement slipped into X."""
    banned_exact = {"volume", "congestion", "speed", "tti", "capacity_util",
                    "env_impact", "target_volume", "target_congestion",
                    "target_class", "Congestion Level", "Traffic Volume"}
    bad = [c for c in feature_cols if c in banned_exact]
    if bad:
        raise AssertionError(f"LEAKAGE: same-day target columns in X -> {bad}")
    if verbose:
        print("   ✅ LEAKAGE CHECK PASSED — all signal columns are lagged or "
              "known-in-advance")


# --------------------------------------------------------------------------
# SERVING PATH — what Django calls
# --------------------------------------------------------------------------
def build_inference_row(
    history_df: pd.DataFrame,
    target_date,
    area: str,
    road: str,
    weather_forecast: str,
    roadwork_planned: bool,
    encoders: dict,
    peer_history: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Produce EXACTLY ONE model-ready feature row for `target_date`.

    history_df : raw-schema rows for this intersection, ascending by date,
                 at least MIN_HISTORY_DAYS long, ending the day BEFORE target_date.
    peer_history : optional raw rows for other intersections (same schema), used
                 for the area/city neighbour features. Falls back gracefully.
    Returns a 1-row DataFrame whose columns match encoders["feature_columns"]
    in exact order.
    """
    target_date = pd.to_datetime(target_date)
    hist = normalize_raw(history_df) if "intersection_id" not in history_df.columns \
        else history_df.copy()
    hist["date"] = pd.to_datetime(hist["date"])
    iid = make_intersection_id(area, road)
    hist = hist[hist["intersection_id"] == iid].sort_values("date")

    if len(hist) < MIN_HISTORY_DAYS:
        raise ValueError(
            f"Need >= {MIN_HISTORY_DAYS} days of history for {iid}, got {len(hist)}")

    # Append a placeholder row for target_date carrying only known-in-advance info.
    stub = hist.iloc[[-1]].copy()
    stub["date"] = target_date
    stub["weather"] = weather_forecast
    stub["roadwork"] = "Yes" if roadwork_planned else "No"
    stub["roadwork_flag"] = int(bool(roadwork_planned))
    for c in ["volume", "speed", "tti", "congestion", "capacity_util",
              "incidents", "env_impact", "pt_usage", "signal_compliance",
              "parking_usage", "ped_count"]:
        stub[c] = np.nan
    frame = pd.concat([hist, stub], ignore_index=True)

    if peer_history is not None and len(peer_history):
        peers = normalize_raw(peer_history) if "intersection_id" not in peer_history.columns \
            else peer_history.copy()
        peers["date"] = pd.to_datetime(peers["date"])
        peers = peers[peers["intersection_id"] != iid]
        frame = pd.concat([frame, peers], ignore_index=True)

    F, _ = build_features(frame, encoders=encoders, fit=False,
                          dropna=False, verbose=False)
    F = F[(F["intersection_id"] == iid) & (F["target_date"] == target_date)]
    if F.empty:
        raise ValueError(f"Could not build a row for {iid} @ {target_date.date()}")

    cols = encoders["feature_columns"]
    row = F.iloc[[-1]][cols].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return row.reset_index(drop=True)
