# Data: what each source is, what it measures, and what the series check found

**Every series the depot twin trains on measures rides that were served, not rides that were wanted. The contracts are code - `depot_twin/data/contracts.py` - and the split registry lives in `data/splits.json` behind `depot_twin/data/registry.py`. Both are checked in CI. This page is the human record of what those files enforce.**

## What every series measures

Every ride record here is a trip that was served. None of them is a trip that was wanted. Where a city's taxis or ride-hail cars were short, real demand was higher than these counts, and the models learn the served figure.

For sizing a depot that's a conservative input. For a forecast it's a definition: we forecast observed transactions, not latent demand.

## What the models are told, by when it is known

| Known at forecast time | Forecast at forecast time | Never used |
|---|---|---|
| The ride series up to now; hour, weekday, weekend, holiday; the tariff period | Temperature and rain for the target hour, taken from Open-Meteo's archive of the forecasts issued at the time (a little better than a real 24-hour forecast; stated in the training notes) | Weather as later observed |

## Provenance

**Every series name says where its rows came from.** Names beginning `generated_` are rows a generator made, and the code refuses them wherever a model is stopped, calibrated or scored, via `contracts.assert_real`. They can only ever be trained on.

There's one exception, by design. The "generated only" arm of E13 stops on generated rows because it has nothing else; it exists to show how far generated data goes alone.

## Sources

| Source | What | Period | Granularity | Licence | Known issues and handling |
|---|---|---|---|---|---|
| San Francisco taxi trips (SFMTA, data.sf.gov `m8hk-2ipk`) | Every taxi trip with start time, distance, fare, pickup position (3 decimals), airport flag. Only the times and positions are used; the fare column is not, because a taxi meter and a robotaxi price are different products (`docs/SITE.md`, "What a ride pays") | Dec 2022 to May 2024 | Exact timestamps; used at 5 minutes and hourly | PDDL | Up to 15% exact duplicate records in some months, removed by exact match; non-ride records (paratransit, zero-length) dropped; a level rise of about 40% early in 2024, flagged and left in |
| New York TLC trip records: ride-hail (fhvhv) and yellow taxi | Pickup time and zone for every trip | Jan 2023 to Jun 2026 | Exact timestamps; counted hourly by area | None stated by the publisher | Each monthly file is downloaded whole, counted and deleted; records dated outside their file's month dropped; the server throttles small requests. Yellow series carry seasonal level swings of 25 to 35% (September up, Christmas down) that are real; two six-hour zero runs at the airports on 23 and 24 September 2023 look like missing data |
| Chicago TNP trips (data.cityofchicago.org `6dvr-xwnh`) | Trip start times, rounded to 15 minutes, whole city | Jan 2025 to Aug 2026 | Hourly, one query per day | City terms of use | Queries by area or before 2025 time out; whole-city only |
| California ISO, OASIS market archive (`PRC_LMP` day-ahead, `PRC_INTVL_LMP` real-time, node `DLAP_PGAE-APND`) | Wholesale prices at the PG&E load point, in dollars a megawatt-hour, by hour (day-ahead) and by five minutes (real-time) | 15 to 28 April 2024 | Hourly and 5 minutes | Public | The archive throttles; requests are paced and cached. Real-time prices go negative at midday and spike in the evening; a depot on a tariff pays neither. Used only as a scenario |
| California ISO, Today's Outlook history | Net demand (demand less wind and solar) and emissions by source, every five minutes | Week of 15 April 2024 (as shipped to the page) | 5 minutes | Public | Exports book as negative emissions and can push a midday total under zero; intensity is floored at zero |
| Open-Meteo historical forecast archive | Temperature and precipitation by hour, as forecast at the time | Covers every ride series | Hourly | Open-Meteo terms (free, attribution) | None found |
| PG&E BEV-2 tariff sheet | Energy prices by period, subscription per 50 kW | Sheet effective March 2026 | Fixed | Public tariff | None |
| CPUC autonomous vehicle quarterly reports | Monthly totals for the driverless fleet in California; the census tracts served each month; counts of chargers and of charging sessions | 2025 Q1 to 2026 Q2 | Monthly; quarterly for chargers and sessions | Public filing | Trip-level fields, trips by tract, charger power and session length are redacted; only totals and counts are used. Charging data covers pilot and deployment fleets together; the file names and folders change every quarter and are matched by pattern |
| Census Bureau: 2020 tract populations with population centroids (CenPop2020), and the 2023 tract gazetteer | Residents and land area by tract, California | 2020 population; 2023 geography | Tract | Public | None found; tract ids in the filings are padded to eleven digits to match |
| PG&E Integration Capacity Analysis map | Headroom on the feeders passing the parcel | Snapshot at build time | Fixed | Public map | A snapshot; an application could return a different figure |

## A pretrained component

| Component | What | Licence | How it is used | Caveat |
|---|---|---|---|---|
| Chronos-2 (Amazon), via `chronos-forecasting` | A pretrained time-series model, used zero-shot and univariate as one point forecast in E18 | Apache 2.0 | The median of its forecast over a context of the last 2,048 hours; no covariates; model files pinned by commit in the result file | Its training corpus includes public mobility series, among them New York taxi data, so a result on New York is an engineering result about an available component, not a zero-shot claim. Chicago's series begins in 2025 and is the cleaner read |

## Daylight saving

All series are in local time, as published. Twice a year that leaves an artefact: the 02:00 hour in March doesn't exist and reads as zero or a few stray records, and the 01:00 hour in November happens twice and is summed into one.

Both are counted in the table below and left as they are. The models see two odd hours a year.

## The series check

It's run with `contracts.audit_table` on every series the models train on. "Regular" means an unbroken index with no duplicate moments. A zero run is six or more consecutive zero hours. A level shift is a four-week mean that moves by more than 25% against the four weeks before it.

| Series | From | To | Step | Regular | Zero runs of 6 h or more | Daylight-saving hours | Level shifts (week, ratio) |
|---|---|---|---|---|---|---|---|
| nyc_ridehail_manhattan_core | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | none |
| nyc_ridehail_upper_manhattan | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | none |
| nyc_ridehail_brooklyn | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | none |
| nyc_ridehail_outer_boroughs | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | none |
| nyc_ridehail_airports | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | none |
| nyc_ridehail_city | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | none |
| nyc_yellow_manhattan_core | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | 2023-09-25 (1.27); 2023-12-25 (0.74); 2024-09-02 (1.33); 2025-01-20 (1.28); 2025-09-01 (1.28); 2025-12-22 (0.73) |
| nyc_yellow_upper_manhattan | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | 2024-02-12 (1.25); 2024-02-26 (1.3); 2024-06-10 (0.74); 2024-08-26 (1.36); 2025-01-13 (1.47); 2025-04-28 (1.28) |
| nyc_yellow_airports | 2023-01-01 | 2026-06-30 | 60 min | yes | 2023-09-23 (6 h); 2023-09-24 (6 h) | 7 | none |
| nyc_yellow_city | 2023-01-01 | 2026-06-30 | 60 min | yes | none | 7 | 2024-09-02 (1.3); 2025-01-20 (1.27); 2025-12-22 (0.75) |
| chicago_ridehail_city | 2025-01-01 | 2026-08-31 | 60 min | yes | none | 3 | none |
| sf_taxi_core | 2022-12-01 | 2024-05-31 | 60 min | yes | none | 3 | 2024-01-22 (1.6) |
| sf_taxi_rest | 2022-12-01 | 2024-05-31 | 60 min | yes | none | 3 | 2024-01-15 (1.38) |
| sf_taxi_airport | 2022-12-01 | 2024-05-31 | 60 min | yes | none | 3 | none |
| sf_taxi_city | 2022-12-01 | 2024-05-31 | 60 min | yes | none | 3 | 2024-01-22 (1.42) |
| sf_taxi_5min | 2022-12-01 | 2024-05-31 | 5 min | yes | none | 3 | 2024-01-22 (1.42) |

**What it says: every series is regular and unique.** The only runs of zeros are the two six-hour stretches at the New York airports in September 2023. The level shifts are San Francisco's rise early in 2024 and New York yellow's seasons.

Nothing is adjusted. The shifts are in the record and the models are expected to live with them. That's why the forecast's target is a ratio.

## The split registry

`data/splits.json` lists every window of every series with its purpose: development, which we look at freely, and test, scored by the tests registered for it. Any other look at a window is written on it.

The Chicago and New York windows of 5 January to 1 March 2026 are the forecast confirmation windows: E17 scores the ride-hail series, and E18 confirms on New York yellow taxi and takes a second look at E17's, labelled exploratory.

One accepted overlap is recorded with its reason: E15 ran the depot on New York days that E13 had used to develop a forecast. Different questions.
