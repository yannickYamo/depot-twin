"""Train the recall policy.

Training runs on a quarter-scale copy of the 1,000-vehicle scenario: the same power per vehicle, the same
chargers per vehicle, a quarter of the vehicles. An episode is four times cheaper, and because the policy
only sees shares and ratios, what it learns carries to the full-size fleet. Whether it actually does is a
registered evaluation, not an assumption.
"""

from __future__ import annotations

from pathlib import Path

TRAIN_SCENARIO = "scenarios/train_quarter_scale.toml"
SHAPE = "data/derived/weekly_shape.json"
MODEL_PATH = "data/derived/recall_policy.zip"


def make_env(rank: int):
    """Return a factory for one training environment with its own run of seeds."""

    def factory():
        from depot_twin.first_version.env import DepotEnv

        return DepotEnv(TRAIN_SCENARIO, SHAPE, first_seed=1000 + rank * 100_000)

    return factory


def train(steps: int = 200_000, workers: int = 8, out: str | Path = MODEL_PATH) -> Path:
    """Train with PPO and save the policy."""
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env import SubprocVecEnv, VecMonitor

    env = VecMonitor(SubprocVecEnv([make_env(rank) for rank in range(workers)]))
    model = PPO(
        "MlpPolicy",
        env,
        n_steps=168,  # one week per worker per update
        batch_size=336,
        gamma=0.995,  # an hour's choice pays off half a day later
        learning_rate=3e-4,
        ent_coef=0.01,
        seed=7,
        device="cpu",
        verbose=1,
    )
    model.learn(total_timesteps=steps)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(out))
    env.close()
    return out


if __name__ == "__main__":  # the first version's trainer, run on its own: python -m depot_twin.first_version.train
    import argparse

    parser = argparse.ArgumentParser(description="Train the first version's learned recall policy.")
    parser.add_argument("--steps", type=int, default=200_000)
    parser.add_argument("--workers", type=int, default=8)
    arguments = parser.parse_args()
    print(f"wrote {train(steps=arguments.steps, workers=arguments.workers)}")
