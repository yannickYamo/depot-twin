# Related work

**TL;DR: the charging literature optimizes energy delivered by a deadline, and none of it that I found models a depot with a grid limit, a queue, cleaning and people who unplug cars. This page lists what I read, what I took, and where this project leaves the literature behind. Sources were gathered on 2026-10-04. Sources marked *(read)* I opened; those marked *(cited)* I know from citations or summaries, and I still need to read them before I quote them anywhere else.**

## Sharing power among vehicles

- Adaptive Charging Network. Lee et al., "Adaptive Charging Networks: A Framework for Smart EV Charging", 2020 *(read)*, https://arxiv.org/abs/2012.02636. A convex program solved in a rolling loop; terms for charging quickly, energy cost, peak draw. Within 0.4% of the best possible schedule on energy delivered. Equal sharing appears only as a tie-breaker.
- ACN-Sim. Lee, Sharma, Johansson and Low, 2020 *(read)*, https://arxiv.org/abs/2012.02809. The standard baselines: uncontrolled, round robin, first come first served, earliest deadline first, least laxity first. For one vehicle, first come first served charges it faster than the deadline rules; round robin slowest.
- Scheduling theory. Serving the job with the least work remaining is optimal for average time in the system (Schrage 1968 *(cited)*; Bansal and Harchol-Balter 2001 *(read)*, https://www.cs.cmu.edu/~harchol/Papers/Sigmetrics01.pdf). Serving the job with the most remaining makes jobs finish together: the worst case for average completion time.

**"Emptiest vehicle first" is the most-work-remaining rule wearing a depot uniform.** Its loss to in-order feeding in E11, E22 and the staffing study is the textbook result showing up on our yard. What I didn't find in the literature is the interaction with people: vehicles that finish together then wait to be unplugged, and the unplugging is done by hand. The theory also predicts that a third rule, least energy needed first, should beat in-order feeding. E14 tested it and it ties. At a site short of energy both rules use all the power, and rides follow energy delivered, so the ordering stops mattering.

**Where this departs: the charging literature optimizes energy delivered by a deadline, and a robotaxi has no deadline.** The objective here is vehicles back on the road. I also don't compare any result here against the best achievable schedule, so nothing on this page should be read as an optimality claim.

## Running a shared electric fleet

- Zhang and Pavone, queueing model of mobility on demand, 2014 *(read)*, https://arxiv.org/abs/1404.4391
- H. Zhang, Sheppard, Lipman and Moura, joint fleet and charger sizing, 2018 *(read)*, https://arxiv.org/abs/1811.00234: about 8 vehicles per 100 kW charger
- Bauer, Greenblatt and Gerke, electric taxi fleets in Manhattan, 2018 *(read)*, https://ees.lbl.gov/publications/cost-energy-and-environmental-impact
- Rossi, Iglesias, Alizadeh and Pavone, fleets and the power network, 2017 *(read)*, https://arxiv.org/abs/1709.04906
- Loeb, Kockelman and Liu, Austin, 2018 *(cited)*: about 20% of miles empty, a third of those to chargers
- Ma and Fang, survey of charging scheduling and fleet management, 2021 *(read)*, https://arxiv.org/abs/2112.04221: the usual metrics

These papers size chargers spread across a city, and they're the right shape for a planning question at that scale. But I found none that models one depot with a single grid limit, a queue, cleaning and staff together, and that combination is the whole of our operating problem.

## Depots in practice

- Electric bus depots: Lepre, Burget and McKenzie, "Deploying Charging Infrastructure for Electric Transit Buses", 2022 *(read)*. Plugging in by hand is a stated burden at 50 vehicles and up; one agency added shifts only to unplug buses.
- Widmer et al., "Optimal Electric Bus Depot Charging", 2026 *(read)*, https://arxiv.org/abs/2607.29304: managed charging cuts required grid capacity by over 40%. No labor.
- NREL HIVE *(read)*, https://github.com/NREL/hive: the closest open simulator; fleet dispatch and charging stations, no cleaning or staff. Archived in June 2026.

The bus people got there first on the part that hurts. An agency adding shifts purely to unplug buses is the same failure E11 reproduces, which is reassuring and slightly depressing. Widmer gives us the headline number for managed charging without labor in the loop. HIVE is the closest open thing to what we're building, and it was archived in June 2026.

## Pretrained time-series models

- Ansari et al., Chronos (Amazon), 2024 *(cited)*, https://arxiv.org/abs/2403.07815; Chronos-2, 2025 *(read: model card)*, https://huggingface.co/amazon/chronos-2. Apache 2.0. Zero-shot forecasting of univariate and multivariate series with optional covariates.
- Traffic-Demand-Bench (tjtrans), 2025 to 2026 *(read: README and results at the commit used)*, https://huggingface.co/datasets/tjtrans/Traffic-Demand-Bench. Hourly taxi and bike pickups by zone in seven systems; published results put Chronos-2 zero-shot ahead of every city-trained model, at 0.61 to 0.72 of the weekly-average rule's error. The benchmark is being updated; figures quoted here as read on 2026-10-05.

**A pretrained model is a legitimate component to try, not a transfer-learning claim.** E18 tries Chronos-2 on the one question that matters at this depot: the reserve a bound asks of the fleet at a required reliability. New York series are in its training corpus, so I don't claim zero-shot transfer from that benchmark result. What E18 reports is narrower and more honest: whether an available off-the-shelf component helps the operating system we actually run.

## Public figures against this model's inputs

| Input | This model | Public figure | Source |
|---|---|---|---|
| Energy in service, per mile | 0.53 kWh (sensitivity study, 700 vehicles) | 0.49 to 0.60, estimated, not measured | Ride AI, 2026 *(read)* |
| Sensors and computer | 1.8 to 2.0 kW always on | about 1 kW; 0.84 to 3 in the literature | same |
| Charger power at the depot | 60 kW | 30 to 60 kW | GovTech 2022; K. Chen 2024 *(read)* |
| Grid connection | 2.75 MW per feeder | 2 to 5 MW at San Francisco sites | same; developer case study *(read)* |
| Rides per vehicle per day | 25 | 18 to 24 | CPUC data via Driverless Digest *(read)* |
| Depot visits per vehicle per day | 3.2 at the filings' cadence (E22); under long sessions 1.5 at 500 vehicles and 1.3 at 700 | 2 to 3 (one operator's planning figure) | secondary *(read)* |
| Plugging in | by a person | by a person | GovTech; Electrek 2026 *(read)* |
| Energy prices | PG&E BEV-2-P, sheet of March 2026 | same | PG&E tariff *(read)* |

One input sits at the edge of what is public: rides per vehicle is high. The sensitivity study in `EVALS.md` moves it, and E22 sets the visit cadence to what the filings count. Read both before you quote any number from the table above as a result.

## Forecasting rides, and a place with no history

- Practice: Uber describes boosted trees and classical methods, with seasonal baselines and prediction intervals always reported ("Forecasting at Uber" *(read)*, https://www.uber.com/blog/forecasting-introduction). Pooled tree models won the M5 competition *(cited)*.
- New cities: RegionTrans (Wang et al. 2019 *(read)*, https://arxiv.org/abs/1802.00386) and MetaST (Yao et al. 2019 *(read)*, https://arxiv.org/abs/1901.08518) transfer between cities but need some data from the target.
- Level from covariates: Yan, Liu and Zhao 2020 *(cited)* predict ride-hail trips in Chicago from demographics, land use and transit.
- Intervals under shift: Tibshirani et al. 2019 *(read)*, https://arxiv.org/abs/1904.06019; Gibbs and Candes 2021 *(read)*, https://arxiv.org/abs/2106.00170. Neither gives a guarantee before real data arrives.
- Open data with recent trips: New York (taxi and ride-hail), Chicago (ride-hail), San Francisco (taxi), Washington DC (taxi). No trip-level data found for Los Angeles or Phoenix.

The transfer methods all want some data from the target city, and a depot we haven't opened yet has none. Yan gives a route to the level from covariates alone; the conformal work gives intervals, but not a guarantee that holds before the first real trip. I found no published method for validating a forecast for a city with no data at all, which is the honest state of this section. The plan in the roadmap borrows the standard answer from other fields: hold out each city that does have data, pretend it has none, measure. The missing method didn't go away. It moved into our evaluation design, and it's ours to answer for.
