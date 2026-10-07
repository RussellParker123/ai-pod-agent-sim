"""Configurable worker assignments for the simulation pipeline."""
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from app.sim.agents import Design


DEFAULT_WORKERS = {
    "trend": ["trend-1", "trend-2"],
    "prompt": ["prompt-1", "prompt-2"],
    "image": ["image-1", "image-2"],
    "compliance": ["compliance-1", "compliance-2"],
    "mockup": ["mockup-1", "mockup-2"],
    "pricing": ["pricing-1", "pricing-2"],
}


@dataclass
class AgentTeam:
    workers: Dict[str, List[str]] = field(
        default_factory=lambda: {department: list(ids) for department, ids in DEFAULT_WORKERS.items()}
    )
    manager_id: str = "manager-1"
    assignments: List[Dict] = field(default_factory=list, init=False)

    def __post_init__(self):
        for department, worker_ids in self.workers.items():
            if not worker_ids or any(not worker_id for worker_id in worker_ids):
                raise ValueError(f"Department '{department}' must have named workers")
            if len(set(worker_ids)) != len(worker_ids):
                raise ValueError(f"Department '{department}' contains duplicate worker IDs")

    def run_stage(self, department: str, designs: List[Design], worker_fn: Callable, **kwargs):
        worker_ids = self.workers.get(department)
        if not worker_ids:
            raise ValueError(f"No workers configured for department '{department}'")

        buckets = [designs[index::len(worker_ids)] for index in range(len(worker_ids))]
        for worker_id, items in zip(worker_ids, buckets):
            if items:
                worker_fn(items, **kwargs)
            self.assignments.append(
                {"department": department, "worker_id": worker_id, "design_count": len(items)}
            )

    def report(self) -> Dict:
        return {
            "manager_id": self.manager_id,
            "departments": {name: list(ids) for name, ids in self.workers.items()},
            "assignments": list(self.assignments),
        }
