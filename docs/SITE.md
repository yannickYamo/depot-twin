# The site and what is known about it

**Every figure on this page is rebuilt by `depot-twin data` into `data/derived/`, with its source and fetch date.** If you cloned the repository, that command is the only thing standing between you and the numbers below. If you're on the fleet operations side, read this as the list of what the model believes and where each belief came from.

## The parcel

A hypothetical depot at 7825 San Leandro Street, Oakland: the former foundry parcel, about 14.5 acres, zoned general industrial, in the corridor south of the Coliseum. I picked it because the parcel, its zoning and the grid around it are all on the public record. Nothing here says the parcel is available.

## Grid headroom

PG&E publishes, for each section of each distribution feeder, how much new load it can take. These are the sections within 150 m of the parcel, fetched 2026-10-04, from an analysis dated mid-2026.

| Feeder | Voltage | Load headroom |
|---|---|---|
| EDES 1101 | 12 kV | 2,751 to 2,759 kW |
| OAKLAND J 1110 | 12 kV | 2,744 to 2,756 kW |
| EDES 1114 | 12 kV | 912 to 2,334 kW |
| OAKLAND J 1104 | 12 kV | 1,158 kW |

What that means for the depot:

- **One service connection: about 2.75 MW.** That's the site limit in the base scenarios.
- **A second service on the other strong feeder: about 5.5 MW.** No feeder in the wider area shows more than about 4.6 MW. The page's power control runs from 1 MW, the weakest feeder nearby, to 5.5 MW, and no further. The limits of the twin are the limits of this place.
- **What the site draws of it: 95%.** The published figure is what the utility can deliver at the parcel, and it already carries the utility's own planning margins - PG&E plans feeders to at most 67% of thermal rating and transformers to under 80% under normal conditions, so load can be moved in a contingency. On the depot side, chargers are a continuous load under the electrical code, and with an automatic load manager the service is sized for the load the manager permits (NEC 625.42); the manager keeps a margin under the agreed figure for metering and response. So the twin's load manager draws at most 95% of the connection (`DepotConfig.usable_share`), an assumption in line with practice. If you'd rather read the figure as an equipment rating, the code's continuous-load rule would make it 80%, and the parameter is there for that reading.
- **How many plugs.** The grid bounds power, not plugs: a load manager may plug in more vehicles than it feeds at once, and paired dispensers share one power cabinet. Two plugs for each one the usable connection feeds - 80 at 60 kW on one feeder - is the most that pays. Past that the extra plugs idle; E19 found half as many again bought nothing. The local tool and the trace recorder hold designs to that figure. The page lets a visitor go past it and says so, and it also says when a fleet is larger than the site sustains, when chargers are too few or too many for the fleet, when people are too few, and what the running depot lost in the last day and which resource bound it.
- **A 2,000-vehicle fleet needs several times that.** Past the point where the feeders run out you're into a battery buffer, a second site, or a substation upgrade that takes years. Finding that point is the purpose of the growth study.

## What the filings count: the visit cadence and the demand around the parcel

Waymo's quarterly filings to the CPUC redact trips by tract, charger power and session length, and leave three things in the open: the census tracts served each month, the number of chargers and the number of charging sessions. Read with the Census Bureau's 2020 tract populations (`depot-twin data footprint`; the record is `data/derived/footprint.json`):

| Quarter | Trips a day | Residents served | Trips a resident a month | Chargers | Sessions a day | Trips a session | Sessions a charger-day |
|---|---|---|---|---|---|---|---|
| 2025 Q1 | 20,200 | 5.73 M | 0.106 | 138 | 2,160 | 9.3 | 15.7 |
| 2025 Q2 | 24,560 | 5.73 M | 0.130 | 155 | 2,620 | 9.4 | 16.9 |
| 2025 Q3 | 29,090 | 7.16 M | 0.125 | 226 | 3,260 | 8.9 | 14.4 |
| 2025 Q4 | 40,750 | 7.16 M | 0.174 | 251 | 4,840 | 8.4 | 19.3 |
| 2026 Q1 | 43,400 | 7.16 M | 0.182 | 263 | 5,540 | 7.8 | 21.0 |
| 2026 Q2 | 46,370 | 7.16 M | 0.197 | 324 | 6,220 | 7.5 | 19.2 |

Charging data covers the whole passenger fleet, pilot and deployment; trips are the deployment's. The twin reproduces this cadence (E22) when vehicles are called in at 55% charge, released at 85% and cleaned every fourth visit, on a five-minute leg (cleaned every second visit it serves 99.7% of rides): 3.2 visits a vehicle-day of 8 trips each. Under that cadence one feeder carries about 600 vehicles at the 99% floor; under long sessions (called in at 20%, cleaned every visit, a fifteen-minute leg) it carries 700.

The service area around the parcel, as circles over Alameda County tracts, at the last four quarters' penetration (0.169 trips a resident a month) and the growth measured at a constant footprint (5.2% a month, a scale-up rate; half of it is shown beside it): 8 km (East Oakland, San Leandro and Alameda; downtown Oakland is 9 km out) holds 421,000 residents and about 2,350 rides a day (94 vehicles; a second feeder in 37 or 73 months); 15 km (Oakland, Emeryville, Hayward), 912,000 and 5,080 (203 vehicles; 22 or 43 months); 20 km (Alameda County's East Bay, to Union City), 1,082,000 and 6,030 (241 vehicles; 19 or 36 months). San Francisco's tracts across the bay and Contra Costa's fall inside 20 km and are left out. No density adjustment is applied; a service area sparser than the served footprint likely produces less (E21).

## Electricity price

PG&E business electric vehicle rate BEV-2, primary voltage, effective 1 March 2026: $0.360 per kWh from 4 pm to 9 pm, $0.151 off-peak, $0.128 from 9 am to 2 pm, plus $85.98 a month for each 50 kW of subscribed capacity.

## The fleet's filed behaviour

From the monthly table in Waymo's filings with the California Public Utilities Commission, April to June 2026, statewide driverless service.

| Figure | Value |
|---|---|
| Trips | 4.22 million in the quarter |
| Miles per trip, all driving | 6.67 |
| Miles per trip with a passenger | 3.93 |
| Share of miles with a passenger | 58.9% |
| Share of miles driving to a pickup | 14.8% |
| Share of miles with no ride assigned | 26.3% |

Trip times, places and charging records are redacted in these filings. They set totals only.

## The money

The planner uses this to turn rides served and energy bought into a daily contribution. Vehicles, insurance and remote assistance are left out of the comparison: they don't change with how the depot is built.

| Figure | Value | Basis |
|---|---|---|
| What a ride pays | $19.69 on average, the published fare; busy pricing moves the fare between hours, up to 1.3 times the quiet price when the fleet is nearly all busy, and leaves the average on $19.69 | A price model built the way the service builds its prices: base, distance, time and busy pricing, quoted up front. The level is the average Bay Area robotaxi fare in a published price survey, late 2025; the proportions of base, per mile and per minute are that survey's reading, not a rate card; busy pricing starts above 80% of on-road vehicles busy and is capped at 1.3, inside the one to three tenths public descriptions give it. Taxi fares are not used: a meter is a different product |
| Energy | $0.360 peak, $0.151 off-peak, $0.128 midday, per kWh | PG&E BEV-2, primary voltage, 1 March 2026 |
| Capacity subscription | $85.98 a month per 50 kW | Same tariff |
| Fast charger, installed | $40,000 plus $500 per kW ($70,000 at 60 kW) | Published hardware costs of about $28,000 at 50 kW and $75,000 at 150 kW, plus installation of $20,000 to $60,000 a port. Assumed split. |
| Slow charger, installed | $8,000 | Published range of $3,000 to $12,000 a port |
| Charger and battery life | 10 years, straight line | Assumed |
| Grid connection | $200 per kW of connection, over 20 years | Assumed, inside published ranges for fleet depot service upgrades |
| A vehicle | $60,000 a vehicle-year, run from $30,000 to $100,000 | A parameter. No public all-in figure exists for a robotaxi, and none is claimed |
| Running a vehicle outside the depot | $100 a vehicle-day | A parameter: maintenance, insurance, remote assistance, support, cleaning supplies, software. No public source |
| A lost ride, beyond its fare | $20, run from $0 to $60 | A parameter: the rider who does not return, the refund, the regulator. No public source |
| Wholesale scenario | Day-ahead or real-time price at the PG&E load point plus $0.08 per kWh delivery | The prices are public (CAISO); the delivery charge is assumed. A scenario for an operator with a pass-through supply contract, not what a tariff customer pays |
| Stationary battery | $400 per kWh installed | Assumed, within published ranges |
| Person on site | $40 an hour | Regional mean wage for vehicle technicians near $28, with 40% on top. Assumed. |
| Land | $217,500 a month | 14.5 acres at $15,000 an acre; national yard rents run $3,500 to $6,500 and one Oakland listing asks $19,600. Assumed. |

## What is assumed, not sourced

| Assumption | Value | Why |
|---|---|---|
| Energy per mile | 0.30 and 0.27 kWh driving, by vehicle type, plus 2.0 and 1.8 kW always on. In service this comes to 0.53 kWh a mile (sensitivity study, 700 vehicles). | The stock vehicle is rated 0.39 to 0.45; public estimates for the robotaxi run 0.49 to 0.60. No measurement is published. |
| Fast-charge power accepted by the newer vehicle | 150 kW | Its pack is 93 kWh at 800 V; no charging figure is published. |
| Fast-charge curve of the older vehicle | 100 kW to 40%, 70 kW at 60%, 50 kW at 80%, 35 kW at 90% | Owner reports, not a dataset. |
| Demand by hour | Replayed from San Francisco taxi days; for a site with no history, generated from New York, Chicago and San Francisco | No public hourly ride-hail data exists for the East Bay. |
| Trip length | 4.92 miles to pickup and with a passenger | The filed average. Not varied, so the planner cannot say what longer trips would do. |
| A rider's wait | Up to ten minutes for a free vehicle; after that the ride is lost | Assumed. |
| Inspection | Every tenth of a vehicle's own visits, 20 minutes | Assumed. |

## Ride records used

| City | What | Period | Source | Terms |
|---|---|---|---|---|
| San Francisco | Taxi trips, with pickup position | December 2022 to May 2024 | City open data, dataset `m8hk-2ipk` | Public Domain Dedication and License |
| New York | Ride-hail and yellow taxi trips, with pickup zone | January 2023 to June 2026 | Taxi and Limousine Commission trip records | Published without an explicit licence |
| Chicago | Ride-hail trips | January 2025 to August 2026 | City data portal, dataset `6dvr-xwnh` | City terms of use |

| California | Grid net demand and emissions, every five minutes | Week of 15 April 2024 | California ISO, Today's Outlook history | Public |

None of the ride records are stored in the repository. The grid week is one small file of two series, read by the front end. The loaders fetch the rest, reduce them to counts, keep only the counts, and leave them outside version control.
