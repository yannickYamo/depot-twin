"""Work built on the first version of the simulator, kept for the record.

A stand-in model of the simulator and a search over depot designs (evaluations E3 to E5), and a recall
policy trained by reinforcement learning (E2). All of it was built before two things changed underneath:
power is now fed in order, and demand is replayed from real days. The results are reported in EVALS.md with
that label. Nothing in the current controller, forecasts or front end depends on this package.
"""
