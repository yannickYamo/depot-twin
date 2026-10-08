"""Forecasts for a site with no ride history, and the test of whether that can work.

Two things live here. `leave_city_out` treats a city that does have data as if it had none: demand is
generated for it from the other cities, a forecast is trained without it, and both are then compared with
what really happened there. `build_site` does the same for a real new site, where there is nothing to
compare with, and says what the held-out cities suggest its error will be.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from depot_twin import synth
from depot_twin.data import donors as donor_data
from depot_twin.data.donors import Donor
from depot_twin.features import BASELINES
from depot_twin.models import short_horizon, transfer

TEST_DAYS = 60
MIN_WEEKS = 20  # a donor with less history than this before the cutoff is not used
GENERATED_SERIES, GENERATED_WEEKS = 6, 52
SITE_LEVELS = (0.5, 2.0)  # around a known level, generated series run from half of it to twice it
THIN_LEVELS = (300, 2000)  # rides an hour; large donors are also trained on at these sizes
LEVEL_RANGE = (300.0, 30000.0)  # rides an hour; generated series are spread across it on a log scale


def weather_for(place: str | tuple[float, float, str], first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
    """Return hourly weather over a span of time, for a named place or (latitude, longitude, time zone)."""
    from depot_twin.data import weather

    return pd.DataFrame(weather.fetch_hours(place, first.date(), last.date())).set_index("time")


def eligible(donors: list[Donor], kind: str, without_city: str | None = None) -> list[Donor]:
    """Return donors of a kind from other cities, falling back to the nearest kind that has any."""
    pool = [d for d in donors if d.city != without_city]
    for wanted in (kind, *donor_data.NEAREST_KIND[kind]):
        found = [d for d in pool if d.kind == wanted]
        if found:
            return found
    return pool


@dataclass
class Sources:
    """The panel with the weather of every donor city, loaded once."""

    panel: pd.DataFrame
    donors: list[Donor]
    weather: dict[str, pd.DataFrame]

    @classmethod
    def load(cls) -> Sources:
        """Load the panel and each donor city's weather over the span of its series."""
        panel, donors = donor_data.load_panel(), donor_data.donors()
        weather = {}
        for place in {d.weather for d in donors}:
            columns = [d.name for d in donors if d.weather == place]
            span = panel[columns].dropna(how="all").index
            weather[place] = weather_for(place, span.min(), span.max())
        return cls(panel, donors, weather)

    def series(self, name: str, until: pd.Timestamp | None = None) -> pd.Series:
        """Return one series, optionally only the part before a moment."""
        series = self.panel[name].dropna()
        return series if until is None else series[series.index < until]

    def profiles(self, donors: list[Donor], until: pd.Timestamp | None = None) -> list[synth.Profile]:
        """Return a profile for each donor that has enough history before the cutoff."""
        out = []
        for donor in donors:
            series = self.series(donor.name, until)
            if len(series) >= MIN_WEEKS * synth.WEEK:
                out.append(synth.extract(donor.name, series, self.weather[donor.weather]))
        return out

    def alike(self, kind: str, rides_per_hour: float, without_city: str | None, until=None) -> set[str]:
        """Return the donor series that resemble a place: its kind, each at the size nearest its own."""
        names = set()
        for donor in eligible(self.donors, kind, without_city):
            versions = sized(donor.name, self.series(donor.name, until))
            names.add(min(versions, key=lambda name: abs(np.log(versions[name].mean() / rides_per_hour))))
        return names

    def rows(self, donors: list[Donor], horizon: int, until: pd.Timestamp | None, by: str) -> dict[str, pd.DataFrame]:
        """Return model rows for the donors, grouped by city or by service.

        Each large donor appears at its own size and again thinned to smaller ones, so that the model sees
        the same rhythms with more and with less counting noise.
        """
        groups: dict[str, list] = {}
        for donor in donors:
            series = self.series(donor.name, until)
            if len(series) < MIN_WEEKS * synth.WEEK:
                continue
            for name, version in sized(donor.name, series).items():
                rows = transfer.rows_for(name, version, horizon, self.weather[donor.weather], until)
                groups.setdefault(getattr(donor, by), []).append(rows)
        return {name: pd.concat(frames) for name, frames in groups.items()}


def sized(name: str, series: pd.Series) -> dict[str, pd.Series]:
    """Return a series at its own size and thinned to each smaller training size, by name."""
    out = {name: series}
    for level in THIN_LEVELS:
        if series.mean() >= 2.0 * level:
            out[f"{name}@{level}"] = thinned(series, float(level), seed=level)
    return out


def monday_before(moment: pd.Timestamp, weeks: int) -> pd.Timestamp:
    """Return the Monday midnight that leaves `weeks` whole weeks before a moment."""
    last_monday = (moment - pd.Timedelta(days=moment.dayofweek)).normalize()
    return last_monday - pd.Timedelta(weeks=weeks)


def thinned(series: pd.Series, rides_per_hour: float, seed: int) -> pd.Series:
    """Return what a small operator would see of a series: each ride kept with the same small chance.

    A depot serves a share of a city's rides, not all of them. Keeping each real ride at random with a
    fixed chance gives a real city's rhythm at a depot's scale, with the counting noise that scale brings.
    """
    chance = min(1.0, rides_per_hour / series.mean())
    kept = np.random.default_rng(seed).binomial(series.to_numpy().astype(int), chance)
    return pd.Series(kept.astype(float), index=series.index)


def generated_series(
    profiles: list[synth.Profile],
    until: pd.Timestamp,
    weather: pd.DataFrame | None,
    seed: int,
    levels: tuple[float, float] = LEVEL_RANGE,
) -> list[pd.Series]:
    """Return a handful of generated series ending at `until`, each a different mix at a different level."""
    rng = np.random.default_rng(seed)
    start = monday_before(until, GENERATED_WEEKS)
    low, high = np.log(levels[0]), np.log(levels[1])
    return [
        synth.generate(profiles, start, GENERATED_WEEKS, float(np.exp(rng.uniform(low, high))), rng, weather)
        for _ in range(GENERATED_SERIES)
    ]


def generated_without(
    profiles: list[synth.Profile],
    until: pd.Timestamp,
    weather: pd.DataFrame | None,
    seed: int,
    horizon: int,
    levels: tuple[float, float] = LEVEL_RANGE,
):
    """Return a builder of generated rows that leaves named donor series out of the mix.

    The cross-city model sizes its bounds by holding each donor group out in turn. Generated demand is
    mixed from donor profiles, so the rows used in a fold are generated again from the donors that fold
    keeps. Asked to leave nothing out, it returns the rows the final model trains on. Builds are kept, since
    the same fold is asked for more than once.
    """
    built: dict[frozenset[str], pd.DataFrame | None] = {}

    def rows(without: frozenset[str] = frozenset()) -> pd.DataFrame | None:
        if without not in built:
            kept = [p for p in profiles if p.name not in without]
            made = generated_series(kept, until, weather, seed, levels) if kept else []
            built[without] = generated_rows(made, horizon, weather) if made else None
        return built[without]

    return rows


def generated_rows(series: list[pd.Series], horizon: int, weather: pd.DataFrame | None) -> pd.DataFrame:
    """Return generated series as model rows."""
    return pd.concat(transfer.rows_for(f"generated_{k}", s, horizon, weather) for k, s in enumerate(series))


def _donor_groups(sources: Sources, city: str, horizon: int, cutoff: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Return the other cities' rows grouped by city, or by service when only one other city has data."""
    others = [d for d in sources.donors if d.city != city]
    groups = sources.rows(others, horizon, cutoff, by="city")
    return groups if len(groups) > 1 else sources.rows(others, horizon, cutoff, by="service")


def _synthetic_only(extra: pd.DataFrame, horizon: int) -> transfer.SiteForecast:
    """The arm trained on generated rows alone. It stops on the last weeks of those rows, by exception:
    it has nothing real, and it exists only to show how far generated data gets on its own."""
    parts = [
        (
            rows[rows.index <= rows.index.max() - pd.Timedelta(days=transfer.STOP_DAYS)],
            rows[rows.index > rows.index.max() - pd.Timedelta(days=transfer.STOP_DAYS)].assign(series="stop_only"),
        )
        for _, rows in extra.groupby("series")
    ]
    model, params = transfer.fit_pooled(pd.concat(p[0] for p in parts), pd.concat(p[1] for p in parts))
    return transfer.SiteForecast(horizon, model, transfer.FEATURES, params, scale_free=True)


def forecast_without(sources: Sources, target: Donor, horizon: int) -> transfer.SiteForecast:
    """Return the forecast for a city as if it had no history: other cities and generated demand only.

    Built exactly as the arm E13 puts its bars on, with the same cutoff: nothing from the city's last 60
    days, or from other cities after they begin, is used.
    """
    full = sources.series(target.name)
    local = sources.weather[target.weather]
    parts = short_horizon.blocks(transfer.rows_for(target.name, full, horizon, local), horizon)
    cutoff = parts["holdout"].index.min()
    groups = _donor_groups(sources, target.city, horizon, cutoff)
    profiles = sources.profiles(eligible(sources.donors, target.kind, target.city), cutoff)
    extra = generated_without(profiles, cutoff, local, len(target.name), horizon)
    # The level that picks the donors most like this city is read before the cutoff, like everything else here.
    like = sources.alike(target.kind, float(full[full.index < cutoff].mean()), target.city, cutoff)
    return transfer.fit_site(horizon, groups, extra, like)


def leave_city_out(
    sources: Sources, target: Donor, horizon: int, development: bool = False, rides_per_hour: float | None = None
) -> dict:
    """Score every arm on one city's last 60 days, with that city left out of everything it could leak into.

    In development the city's real last 60 days are cut off first, so the days scored are the 60 before
    them and the test days stay unseen. With rides_per_hour, the city is first thinned to that level, to
    score at the scale of a depot instead of a city, and demand is generated around that level.
    """
    full = sources.series(target.name)
    if development:
        full = full[full.index < full.index.max() - pd.Timedelta(days=TEST_DAYS)]
    levels = LEVEL_RANGE
    if rides_per_hour is not None:
        full = thinned(full, rides_per_hour, seed=horizon)
        levels = (rides_per_hour * SITE_LEVELS[0], rides_per_hour * SITE_LEVELS[1])
    local = sources.weather[target.weather]
    parts = short_horizon.blocks(transfer.rows_for(target.name, full, horizon, local), horizon)
    held, cutoff = parts["holdout"], parts["holdout"].index.min()
    actual = held["label"].to_numpy()
    in_city = short_horizon.fit(parts, horizon, features=transfer.FEATURES, scale_free=True)

    groups = _donor_groups(sources, target.city, horizon, cutoff)
    profiles = sources.profiles(eligible(sources.donors, target.kind, target.city), cutoff)
    extra = generated_without(profiles, cutoff, local, len(target.name), horizon, levels)
    made = generated_series(profiles, cutoff, local, seed=len(target.name), levels=levels)
    like = sources.alike(target.kind, float(full[full.index < cutoff].mean()), target.city, cutoff)
    donors_only = transfer.fit_site(horizon, groups, like=like)
    arms = {
        "donors_only": donors_only,
        "donors_and_generated": transfer.fit_site(horizon, groups, extra, like, donors_only.params),
        "generated_only": _synthetic_only(extra(), horizon),
    }
    naive = {name: round(short_horizon.wape(actual, held[column].to_numpy()), 4) for name, column in BASELINES.items()}
    return {
        "city": target.city,
        "series": target.name,
        "horizon": horizon,
        "rides_per_hour": rides_per_hour,
        "test_days": [str(held.index.min().date()), str(held.index.max().date())],
        "donor_groups": {name: int(rows["series"].nunique()) for name, rows in groups.items()},
        "naive": naive,
        "best_naive": min(naive.values()),
        "in_city": round(short_horizon.wape(actual, in_city.predict(held)), 4),
        **{name: transfer.score(forecast, held) for name, forecast in arms.items()},
        "bounds": {
            "upper_relative": round(arms["donors_and_generated"].upper_relative, 4),
            "lower_relative": round(arms["donors_and_generated"].lower_relative, 4),
            "trust": {name: round(forecast.trust, 2) for name, forecast in arms.items()},
        },
        "likeness": synth.likeness(made, full[full.index < cutoff]),
    }


SITE_SERIES = 6
REPLAY_WEEKS, HISTORY_WEEKS = 2, 3  # each demand file replays two weeks, after three the forecast can look back on


@dataclass
class Site:
    """A place with no ride history: where it is, what kind of place, and how busy it is expected to be."""

    name: str
    latitude: float
    longitude: float
    timezone: str
    kinds: dict[str, float]  # share of each kind of place in the area served, such as {"outer": 0.6, "inner": 0.4}
    rides_per_hour: float  # the level, averaged over the week. An input: nothing here can estimate it.


def site_profiles(sources: Sources, site: Site) -> tuple[list[synth.Profile], np.ndarray]:
    """Return the donors a site borrows from, with a weight for each: its kind's share, split evenly."""
    profiles, weights = [], []
    for kind, share in site.kinds.items():
        found = sources.profiles(eligible(sources.donors, kind))
        profiles += found
        weights += [share / len(found)] * len(found)
    return profiles, np.array(weights) / np.sum(weights)


def _site_series(site: Site, profiles, weights, start: pd.Timestamp, weeks: int, weather, rng) -> pd.Series:
    """Return one generated series for the site: a random lean within its mix, at a level near the one asked."""
    lean = rng.dirichlet(np.ones(len(profiles)) * 4.0)
    level = site.rides_per_hour * float(np.exp(rng.uniform(*np.log(SITE_LEVELS))))
    return synth.generate(profiles, start, weeks, level, rng, weather, weights=weights * lean)


def site_forecasts(sources: Sources, site: Site, weather: pd.DataFrame, until: pd.Timestamp, seed: int = 0) -> dict:
    """Train the forecast for a site at each horizon, on every donor city and on demand generated for it."""
    profiles, weights = site_profiles(sources, site)
    start = monday_before(until, GENERATED_WEEKS)
    made: dict[frozenset[str], list[pd.Series]] = {}

    def series_without(without: frozenset[str]) -> list[pd.Series]:
        """The site's generated series, mixed only from donors outside the set: a fold's rows owe nothing to its held-out city."""
        if without not in made:
            keep = [k for k, profile in enumerate(profiles) if profile.name not in without]
            rng = np.random.default_rng(seed)
            made[without] = [
                _site_series(
                    site,
                    [profiles[k] for k in keep],
                    weights[keep] / weights[keep].sum(),
                    start,
                    GENERATED_WEEKS,
                    weather,
                    rng,
                )
                for _ in range(SITE_SERIES if keep else 0)
            ]
        return made[without]

    forecasts = {}
    for horizon in short_horizon.HORIZONS:
        groups = sources.rows(sources.donors, horizon, None, by="city")
        like = set().union(*(sources.alike(kind, site.rides_per_hour, None) for kind in site.kinds))

        def beside(without: frozenset[str] = frozenset(), horizon: int = horizon) -> pd.DataFrame | None:
            series = series_without(without)
            return generated_rows(series, horizon, weather) if series else None

        forecasts[horizon] = transfer.fit_site(horizon, groups, beside, like)
    return forecasts


def site_demand(sources: Sources, site: Site, forecasts: dict, weather: pd.DataFrame, until: pd.Timestamp, seed: int):
    """Return two weeks of five-minute demand for the site at the level asked for, with its forecasts.

    The result is in the form the fleet simulation replays: counts, and for every step the next 24 hours
    as the site's forecast saw them then.
    """
    from depot_twin import replay

    profiles, weights = site_profiles(sources, site)
    rng = np.random.default_rng(seed)
    weeks = HISTORY_WEEKS + REPLAY_WEEKS
    start = monday_before(until, weeks)
    hourly = synth.generate(profiles, start, weeks, site.rides_per_hour, rng, weather, weights=weights)
    counts = synth.five_minute(hourly, rng)
    replay_start = start + pd.Timedelta(weeks=HISTORY_WEEKS)
    return replay.forecast_curves(forecasts, counts, weather, replay_start, REPLAY_WEEKS * 7)


def expected_error(result: dict) -> dict:
    """Return, per horizon, what E13's held-out cities suggest for a new site.

    Error is given against "same hour last week" on the same days, because the absolute figure depends on
    how erratic a place is: 1.0 is no better than last week's curve, 0.7 is 30% less error. The range runs
    from the best held-out city to the worst.
    """
    out = {}
    for horizon in short_horizon.HORIZONS:
        cells = [c for c in result["cells"] if c["horizon"] == horizon]
        against = [c["donors_and_generated"]["wape"] / c["naive"]["same_time_last_week"] for c in cells]
        held = [c["donors_and_generated"]["upper_coverage"] for c in cells]
        out[f"{horizon}h"] = {
            "error_against_last_week_best": round(min(against), 3),
            "error_against_last_week_worst": round(max(against), 3),
            "upper_bound_held_least": min(held),
            "upper_bound_held_most": max(held),
        }
    return out


def load_site_forecasts(folder) -> dict[int, transfer.SiteForecast]:
    """Read back the forecasts `depot-twin new-site` wrote for a site, with their bounds and trust."""
    import json
    from pathlib import Path

    import xgboost as xgb

    folder = Path(folder)
    bounds = json.loads((folder / "site.json").read_text())["bounds"]
    forecasts = {}
    for horizon in short_horizon.HORIZONS:
        model = xgb.XGBRegressor()
        model.load_model(str(folder / f"forecast_site_{horizon}h.json"))
        entry = bounds[f"{horizon}h"]
        forecasts[horizon] = transfer.SiteForecast(
            horizon,
            model,
            transfer.FEATURES,
            {},
            scale_free=True,
            upper_relative=entry["upper_relative"],
            lower_relative=entry["lower_relative"],
            trust=entry.get("trust", 1.0),
        )
    return forecasts
