# Data: one card per source

[Back to the README](../README.md)

*One card per data source: where it comes from, what it counts and what it can't say. For a reader checking an input. The one thing to take: every ride series counts rides served, not rides wanted.*


Every ride series here counts rides that were served, not rides that were wanted; where cars were short, real demand was higher, and the models learn the served figure. Raw files aren't in the repository: they stay under their publishers' terms. `data/manifest.json` lists every downloaded file with its size, SHA-256 and retrieval date (222 files; check with `depot_twin.data.build.manifest_problems()`), and `depot-twin data manifest` rewrites it. For New York the manifest covers the project's hourly counts, because the monthly trip files are deleted once counted; a later revision of those files by the publisher would not show there. The demand and forecast curves of the four replayed fortnights are kept in `data/reproduce/`, and they are part of the stamp every depot result carries.

## What the models are told, by when it is known

| Known at forecast time | Forecast at forecast time | Never used |
|---|---|---|
| The ride series up to the forecast moment; hour, weekday, weekend, holiday; the tariff period | Temperature and rain for the target hour, taken from Open-Meteo's archive of the forecasts issued at the time (a little better than a real 24-hour forecast) | Weather as later observed |

Series named `generated_` are rows a generator made. `contracts.assert_real` refuses them wherever a model is stopped, calibrated or scored; the one exception is the generated-only arm of E13, which has nothing else to stop on.

## Sources

### San Francisco taxi trips
- **Publisher, licence:** City and County of San Francisco (SFMTA), data.sf.gov dataset `m8hk-2ipk`. Public Domain Dedication and License; credited as "City and County of San Francisco, Taxi Trips (DataSF open data)".
- **Row, clock, period, grain:** one taxi trip with start time, distance, meter time, fare, pickup position (3 decimals), airport and paratransit flags. Local time as published, December 2022 to May 2024, exact timestamps; counted at 5 minutes and hourly, by area (core, rest, airport) and city.
- **Cleaning:** paratransit dropped; records under 300 meters or under 60 seconds dropped (meter tests, cancellations); rows that don't parse dropped; exact repeats of a record dropped, up to 15% in some months. Rides with no position count as "rest".
- **Known artefacts:** a break in what is reported from mid-February 2024 (section below). The November clock-change hour is single in this feed.
- **Used by:** E7, E7b, E8 to E13, E16, E19, E20, E22, E23, E25, E26 and E27 in EVALS.md; `web/public/models.json`, `trust.json`, `facts.json`, `money.json`, `traces/`.
- **Not suitable for:** ride-hail levels (these are taxis); pricing a robotaxi ride (a taxi meter is a different product); anything after May 2024; a clean multi-week forecast comparison.

### New York TLC ride-hail and yellow taxi
- **Publisher, license:** New York City Taxi and Limousine Commission, monthly trip record files `fhvhv_tripdata` and `yellow_tripdata`. No license stated by the publisher; credited as "New York City Taxi and Limousine Commission, trip record data".
- **Row, clock, period, grain:** one trip with pickup time and pickup zone. Local time as published, January 2023 to June 2026, exact timestamps; counted hourly in five areas (Manhattan core, upper Manhattan, Brooklyn, outer boroughs, airports) and city. Yellow is kept for the two Manhattan areas, the airports and the city.
- **Cleaning:** each monthly file is downloaded whole, reduced to hourly counts by area and deleted; records dated outside their file's month dropped; zones outside the city or unknown dropped; hours with no record read as zero.
- **Known artefacts:** yellow series carry real seasonal swings of 25 to 35% (September up, Christmas down); two six-hour zero runs at the airports on 23 and 24 September 2023 look like missing data; the November hour is doubled; files appear about two months behind.
- **Used by:** E13, E15, E17, E18, E24; `web/public/facts.json` (through E13).
- **Not suitable for:** a zero-shot reading of a pretrained model (these records are in public pretraining corpora); anything finer than an hour or an area, since only the counts are kept.

### Chicago ride-hail
- **Publisher, license:** City of Chicago, Transportation Network Providers trips, data.cityofchicago.org dataset `6dvr-xwnh`. City terms of use; credited as "City of Chicago, Transportation Network Providers trips (Chicago Data Portal)".
- **Row, clock, period, grain:** trips per hour for the whole city, counted by the portal, one query per day. Local time as published, January 2025 to August 2026, hourly.
- **Cleaning:** none at row level; hours with no record read as zero.
- **Known artefacts:** trip start times are rounded to 15 minutes by the publisher; queries by area or before 2025 time out, so the series is whole-city and starts in 2025; the November hour is doubled.
- **Used by:** E1, E7 (second-city table), E13, E14, E15, E17, E18, E24; `web/public/facts.json` (through E13).
- **Not suitable for:** anything by area or below an hour; the level of demand at the depot (only the shape is taken, the level is rescaled to the simulated fleet).

### CPUC autonomous-vehicle quarterly reports
- **Publisher, license:** California Public Utilities Commission, Waymo's driverless deployment filings, one zip per quarter (`waymo-deployment-2026q2.zip` and its like). Public filing; credited as "California Public Utilities Commission, autonomous vehicle quarterly reports".
- **Row, clock, period, grain:** one month of statewide driverless service (trips, waiting hours, miles with no ride, to a pickup and with a passenger); the census tracts served each month; one row per charger and per charging session, of which only the count is read. 2025 Q1 to 2026 Q2; monthly, and quarterly for chargers and sessions.
- **Cleaning:** file names and folders change every quarter and are matched by pattern; tract ids padded to eleven digits; a quarter's footprint is its month with the most tracts.
- **Known artefacts:** trip-level fields, trips by tract, charger power and session length are redacted; charging data covers pilot and deployment fleets together while trips are the deployment's.
- **Used by:** the fleet's calibration targets (`data/derived/cpuc_targets.json`, latest quarter); E21, E22 (`data/derived/footprint.json`); `web/public/demand.json`.
- **Not suitable for:** anything by hour, by trip or by tract; one city on its own (all service areas are combined); charger power or session length.

### Census tracts
- **Publisher, license:** US Census Bureau, `CenPop2020_Mean_TR06.txt` and `2023_gaz_tracts_06.txt`. Public; credited as "US Census Bureau, 2020 decennial population and 2023 gazetteer".
- **Row, clock, period, grain:** one California tract with its 2020 population, population-weighted centroid and 2023 land area.
- **Cleaning:** the two files are joined on the eleven-digit tract id; served tracts absent from the population file are left out of the residents total.
- **Known artefacts:** none found.
- **Used by:** E21 and `web/public/demand.json`: residents served, density, and the 8, 15 and 20 km service areas around the parcel.
- **Not suitable for:** drive-time catchments (the service areas are straight-line circles over Alameda County tracts only); population after 2020.

### Open-Meteo forecast archive
- **Publisher, license:** Open-Meteo, `historical-forecast-api.open-meteo.com`. CC BY 4.0, free with attribution to Open-Meteo.
- **Row, clock, period, grain:** one hour at one point (San Francisco, Chicago, New York, Oakland) with temperature in Celsius and precipitation in millimetres, as forecast at the time. Local time of the place; covers every ride series; hourly.
- **Cleaning:** hours with no temperature dropped; a missing precipitation value reads as zero.
- **Known artefacts:** the archive stitches together forecasts issued a few hours ahead, so as "the forecast for the target hour" it's a little better than a real 24-hour forecast.
- **Used by:** the weather features of E7, E7b, E13, E17, E18 and E24; `web/public/models.json`.
- **Not suitable for:** observed weather; measuring what a true day-ahead weather forecast is worth.

### California ISO prices and Today's Outlook
- **Publisher, license:** California ISO. OASIS market archive, reports `PRC_LMP` (day-ahead) and `PRC_INTVL_LMP` (real-time) at node `DLAP_PGAE-APND`; Today's Outlook history, tables `netdemand` and `co2`. Public.
- **Row, clock, period, grain:** wholesale price at the PG&E load point in dollars a megawatt-hour, hourly day-ahead and 5-minute real-time; net demand (demand less wind and solar) and emissions by source every 5 minutes. 15 to 28 April 2024. Prices arrive in UTC and are moved to Pacific time at a fixed seven hours.
- **Cleaning:** only the LMP rows of a price report are read; a blank demand reading takes the value before it; each day is cut to 288 steps; carbon intensity is floored at zero. The archive throttles, so requests are paced and cached.
- **Known artefacts:** real-time prices go negative at midday and spike in the evening; exports book as negative emissions and can push a midday total under zero.
- **Used by:** the wholesale price scenarios of E19 and E20; `web/public/grid/california_week.json`, `web/public/money.json`.
- **Not suitable for:** what a depot on a tariff pays (it pays neither price); any other week (the fixed offset holds for daylight time only); forecasting.

### PG&E tariff sheet and capacity map
- **Publisher, license:** Pacific Gas and Electric. Business Electric Vehicle rate sheet (`bev.xlsx`, BEV-2, effective March 2026), a public tariff; Integration Capacity Analysis map, layer `DRPComplianceRelProd/FeatureServer/3`, a public map.
- **Row, clock, period, grain:** tariff: an energy price for each of three periods (peak 4 pm to 9 pm, off-peak, super off-peak 9 am to 2 pm) and a subscription per 50 kW a month. Map: load headroom in kW for each feeder line section within 150 meters of the parcel.
- **Cleaning:** sections with no published capacity are skipped; the rest are grouped by feeder into a lowest and a highest headroom.
- **Known artefacts:** the map is a snapshot queried live, so it isn't in the manifest, and an application could return a different figure; where on the feeder the depot connects decides which end of the range applies.
- **Used by:** the energy and subscription lines of every costed run (E12, E19, E20, E23, E25, E26) and `web/public/money.json`; `data/derived/site.json` for the feeder headroom.
- **Not suitable for:** a connection offer; other rate schedules or later tariff years.

### Demand windows for the site planner (`sites/demand/`)
- **Publisher, license:** derived here from three sources carded above: San Francisco taxi trips, New York TLC ride-hail and Chicago ride-hail, each under its publisher's terms.
- **Row, clock, period, grain:** one hour of city-wide ride counts, local time, fourteen days from a Monday. San Francisco: the study's four fortnights of spring 2024. Chicago and New York: the fortnights from 14 July 2025, 13 October 2025, 12 January 2026 and 13 April 2026.
- **Cleaning:** the hourly counts of the series as loaded, rounded to whole rides. The planner spreads an hour evenly over twelve five-minute steps and uses only the shape: the level is the fleet's rides a vehicle a day.
- **Known artefacts:** city-wide counts are smoother than a depot's own rides would be; the San Francisco files exist to show what counting by the hour alone changes, which is nothing in the fleet carried.
- **Used by:** `sites/shape_*.toml` and the plans in `sites/plans/`.
- **Not suitable for:** the demand of any service area. They are shapes of a week in three cities.

### Obi ride price survey (the fare)
- **Publisher, license:** Obi, a ride price comparison service; figures as reported by TechCrunch, "The price gap between Waymo and Uber is narrowing", 27 January 2026 (`https://techcrunch.com/2026/01/27/the-price-gap-between-waymo-and-uber-is-narrowing/`). A published figure quoted with its source; no file is downloaded.
- **Row, clock, period, grain:** one number, the average price of a Waymo ride in the San Francisco Bay Area: $19.69 over more than 94,000 simulated ride requests between 27 November 2025 and 1 January 2026. The same survey put Uber at $17.47 and Lyft at $15.47, and Waymo at $20.43 in June 2025.
- **Cleaning:** none. The price model's base, per-mile and per-minute parts are scaled so the filed average trip costs this figure.
- **Known artefacts:** quoted prices for simulated requests, not fares paid; five weeks that include the year-end holidays; San Francisco, not the East Bay.
- **Used by:** the account in E19, E20, E23, E25 and E26, and the account study; `web/public/money.json` and `web/public/outcome.json`.
- **Not suitable for:** a rate card (the survey reports an average, and the split into base, distance and time is its reading); fares in another city or another year. The account study moves it 10% each way.

### Chronos-2 (pretrained component)
- **Publisher, license:** Amazon, model `amazon/chronos-2` through the `chronos-forecasting` package. Apache 2.0.
- **What it's:** a pretrained time-series model, used zero-shot and univariate, with no local fitting and no covariates.
- **How it's run:** the median of its forecast over a context of the last 2,048 hours, floored at zero; the hub's commit for the model files is written into the result file when it is made; the loader does not pin a revision, so a later run would take whatever the hub then serves.
- **Known artefacts:** its training corpus includes public mobility series, among them New York taxi data.
- **Used by:** E18 and E24 as one point forecast; `web/public/models.json`, `web/public/trust.json`.
- **Not suitable for:** a zero-shot claim on New York, where a result is an engineering result about an available component. Chicago's series begins in 2025 and is the cleaner read.

## Clock changes

All series are on the local clock. In March the hour from 02:00 does not exist and reads as zero; in November the hour from 01:00 happens twice and, in the New York and Chicago feeds, is summed into one (San Francisco's feed holds a single hour). `contracts.steady_clock` fills the March hour with the mean of the hours either side and halves the doubled November hour, at the point where the series are loaded (`donors.load_panel`, the San Francisco loaders, which pass `doubled_hour=False`, and the two reads that take Chicago straight from `chicago.fetch_hours`, E1's hourly frame and the second-city table of E7); the stored copies stay as the sources give them. No model is trained or scored on the two artefacts.

## A break in the San Francisco series

From mid-February 2024 recorded rides rise by about 45% (4,900 a day in the five weeks before, 7,100 in the five after) while the number of cabs reporting stays flat. It is a change in what is reported, not in demand. Training ends 5 February 2024. The stop block starts on 6 February and straddles the change; the calibration and held-out blocks sit after it. So the San Francisco forecast figures measure a model through a break, the multi-week comparison of forecasts is run on Chicago and New York (E24 in EVALS.md), and the weekly demand shape is built from training days only.

## The series check

`contracts.audit_table` on every series the models train on. "Regular" means an unbroken index with no duplicate moments. A zero run is six or more consecutive zero hours. "Daylight-saving hours" counts the clock-change hours inside the series, handled as above. A level shift is a four-week mean more than 25% away from the four weeks before it, dated to the first week flagged, which is why the San Francisco break shows in late January.

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

Every series is regular and unique. The only zero runs are the two at the New York airports; the level shifts are the San Francisco break and New York yellow's seasons, and both are left in the series.

## Windows

`data/splits.json` lists every window of every series with its purpose: development, looked at freely, or test, scored only by the tests registered for it, with any other look written on the window. The dates in code are held to it by `tests/test_contracts.py`.
