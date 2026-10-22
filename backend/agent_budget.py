"""Per-run staged wall-clock allowance, earned only by fresh useful evidence."""
import hashlib
import json
import time


class PhaseBudget:
    def __init__(self, initial=30, increment=10, *, clock=None, hard_timeout=None):
        self.clock = clock or time.monotonic
        self.started = self.clock()
        self.initial = initial
        self.increment = increment
        self.allowance = initial
        self.hard_deadline = self.started + hard_timeout if hard_timeout is not None else float("inf")
        self.progress = set()

    def remaining(self):
        return max(0, min(self.started + self.allowance, self.hard_deadline) - self.clock())

    def credit(self, tool, result, *, cached=False, draft=False):
        if cached or draft or not isinstance(result,dict) or result.get("error") or self.remaining()<=0:
            return False
        fields = ("devices", "records", "record", "strategies", "evaluation", "series", "events", "maintenance", "fault_intervals")
        data = {key:result[key] for key in fields if result.get(key)}
        if not data: return False
        identity = {"tool":tool,"category":result.get("category"),"data_version":result.get("data_version"),"data":data}
        digest = hashlib.sha256(json.dumps(identity,sort_keys=True,ensure_ascii=False,default=str,allow_nan=False).encode()).hexdigest()
        if digest in self.progress: return False
        self.progress.add(digest)
        self.allowance += self.increment
        return True

    def snapshot(self, active=False):
        return {"mode":"staged_time", "initial_seconds":self.initial, "progress_increment_seconds":self.increment,
                "useful_progress_count":len(self.progress), "run_limit_seconds":self.allowance,
                "current_limit_seconds":self.allowance if active else self.initial,
                "remaining_seconds":round(self.remaining(),2) if active else 0, "active":active,
                "reset_after_run":not active}
