"""Optional pinned NSGA-II proposer; encoder budget counts unique configs.

Duplicate suggestions reuse an already verified training objective. Failed
encoder trials are failed in Optuna and abort the study; no invented score.
"""
import importlib.metadata
import time

from search_cpu import AXES, identity


class NSGAProposer:
    def __init__(self, seed):
        import optuna
        if optuna.__version__ != "4.5.0":
            raise ValueError("use the pinned optuna==4.5.0 research environment")
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        self.optuna = optuna
        self.study = optuna.create_study(directions=["minimize", "minimize"],
            sampler=optuna.samplers.NSGAIISampler(seed=seed, population_size=16))
        self.cached = 0
        self.pending = None
        self.feedback_seconds = 0.0

    def ask(self, trials):
        previous = {t["id"]: t for t in trials}
        for _ in range(10000):
            trial = self.study.ask()
            config = {axis: trial.suggest_categorical(axis, values) for axis, values in AXES.items()}
            key = identity(config)
            trial.set_user_attr("config_id", key)
            if key in previous:
                self.study.tell(trial, self.values(previous[key]))
                self.cached += 1
                continue
            self.pending = trial
            return config
        raise ValueError("NSGA-II duplicate proposal limit reached")

    @staticmethod
    def values(result):
        return [result["aggregate"]["time_vs_paired_balanced"], result["aggregate"]["packed_bytes"]]

    def tell(self, result):
        started = time.perf_counter()
        self.study.tell(self.pending, self.values(result))
        self.pending = None
        self.feedback_seconds += time.perf_counter() - started

    def fail(self):
        if self.pending is not None:
            self.study.tell(self.pending, state=self.optuna.trial.TrialState.FAIL)
            self.pending = None

    def evidence(self):
        return {"optuna": "4.5.0", "population_size": 16, "duplicate_cache_hits": self.cached,
                "feedback_seconds": self.feedback_seconds,
                "dependency_versions": {name: importlib.metadata.version(name) for name in
                    ("optuna", "numpy", "sqlalchemy", "alembic", "PyYAML", "tqdm", "colorlog", "packaging")},
                "trials": [{"number": t.number, "params": t.params, "values": t.values,
                            "state": t.state.name, "config_id": t.user_attrs.get("config_id")}
                           for t in self.study.trials]}
