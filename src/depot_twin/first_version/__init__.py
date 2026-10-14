"""The stand-in model, the design search and the learned recall policy behind tests E2 to E5.

A stand-in model of the simulator and a search over depot designs (evaluations E3 to E5), and a recall
policy trained by reinforcement learning (E2). All of it runs with emptiest-first feeding
and demand drawn from an average week, and EVALS.md reports the results with that setting named. Nothing in the current controller, forecasts or front end depends on this package.
"""
