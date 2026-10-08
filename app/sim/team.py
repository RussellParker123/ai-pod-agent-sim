"""Configurable worker assignments and department transfers for the pipeline.

Each worker has a stable ``agent_id`` that is separate from its *home*
department and its *current* department. ``workers`` always reflects the
current roster, so a transfer changes which agents ``run_stage`` assigns
work to from then on. Transfers are validated (known agent, known
destination department, capability, not mid-task, minimum staffing) and
every move is recorded as an event so the UI replays real state instead of
inventing it.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

LOGGER = logging.getLogger(__name__)

DEFAULT_WORKERS = {
    "prompt": ["prompt-1", "prompt-2"],
    "image": ["image-1", "image-2"],
    "compliance": ["compliance-1", "compliance-2"],
    "mockup": ["mockup-1", "mockup-2"],
    "pricing": ["pricing-1", "pricing-2"],
    "marketing": ["marketing-1"],
    "recycling": ["recycler-1"],
}

# Agents are cross-trained within a skill group and can transfer between
# those departments. Departments outside every group are home-only.
SKILL_GROUPS = {
    "creative": ("prompt", "image"),
    "review": ("compliance", "recycling"),
    "commerce": ("mockup", "pricing", "marketing"),
}
MIN_STAFF = 1


class TransferError(ValueError):
    """Raised for an invalid department transfer."""


def default_capabilities(department: str) -> List[str]:
    caps = {department}
    for members in SKILL_GROUPS.values():
        if department in members:
            caps.update(members)
    return sorted(caps)


def _new_agent(agent_id: str, department: str, capabilities: List[str]) -> Dict:
    return {
        "agent_id": agent_id,
        "home_department": department,
        "current_department": department,
        "capabilities": sorted(set(capabilities) | {department}),
        "status": "idle",
        "temporary": False,
        "history": [],
    }


@dataclass
class AgentTeam:
    workers: Dict[str, List[str]] = field(
        default_factory=lambda: {department: list(ids) for department, ids in DEFAULT_WORKERS.items()}
    )
    manager_id: str = "manager-1"
    capabilities: Optional[Dict[str, List[str]]] = None
    assignments: List[Dict] = field(default_factory=list, init=False)
    agents: Dict[str, Dict] = field(default_factory=dict, init=False)
    events: List[Dict] = field(default_factory=list, init=False)

    def __post_init__(self):
        self.workers = {department: list(ids) for department, ids in self.workers.items()}
        seen: Dict[str, str] = {}
        for department, worker_ids in self.workers.items():
            if not worker_ids or any(not worker_id for worker_id in worker_ids):
                raise ValueError(f"Department '{department}' must have named workers")
            if len(set(worker_ids)) != len(worker_ids):
                raise ValueError(f"Department '{department}' contains duplicate worker IDs")
            for worker_id in worker_ids:
                if worker_id in seen:
                    raise ValueError(
                        f"Worker ID '{worker_id}' appears in both '{seen[worker_id]}' and '{department}'"
                    )
                seen[worker_id] = department
        caps = self.capabilities or {}
        for worker_id, department in seen.items():
            self.agents[worker_id] = _new_agent(
                worker_id, department, caps.get(worker_id) or default_capabilities(department)
            )

    # --- work -------------------------------------------------------------
    def run_stage(self, department: str, designs: List, worker_fn: Callable, worker_kwarg: str = "", **kwargs):
        """Split ``designs`` round-robin across the department's *current*
        workers. If ``worker_kwarg`` is set, the worker's ID is passed to
        ``worker_fn`` under that keyword (so work is attributed to it)."""
        worker_ids = list(self.workers.get(department) or [])
        if not worker_ids:
            raise ValueError(f"No workers configured for department '{department}'")

        buckets = [designs[index::len(worker_ids)] for index in range(len(worker_ids))]
        for worker_id, items in zip(worker_ids, buckets):
            agent = self.agents[worker_id]
            if items:
                agent["status"] = "busy"
                extra = {worker_kwarg: worker_id} if worker_kwarg else {}
                try:
                    worker_fn(items, **kwargs, **extra)
                finally:
                    agent["status"] = "idle"
            self.assignments.append(
                {
                    "department": department,
                    "worker_id": worker_id,
                    "design_count": len(items),
                    "home_department": agent["home_department"],
                }
            )

    # --- movement ---------------------------------------------------------
    def transfer(
        self,
        agent_id: str,
        destination: str,
        reason: str = "",
        initiated_by: str = "user",
        temporary: bool = False,
    ) -> Dict:
        agent = self.agents.get(agent_id)
        if agent is None:
            raise TransferError(f"Unknown agent '{agent_id}'")
        if destination not in self.workers:
            raise TransferError(f"Unknown department '{destination}'")
        source = agent["current_department"]
        if destination == source:
            raise TransferError(f"Agent '{agent_id}' is already in '{destination}'")
        if destination not in agent["capabilities"]:
            raise TransferError(
                f"Agent '{agent_id}' is not trained for '{destination}' "
                f"(can work in: {', '.join(agent['capabilities'])})"
            )
        if agent["status"] != "idle":
            raise TransferError(f"Agent '{agent_id}' is mid-task in '{source}' and cannot move now")
        if len(self.workers[source]) - 1 < MIN_STAFF:
            raise TransferError(f"'{source}' must keep at least {MIN_STAFF} worker(s)")

        self.workers[source].remove(agent_id)
        self.workers[destination].append(agent_id)
        agent["current_department"] = destination
        agent["temporary"] = bool(temporary) and destination != agent["home_department"]
        event = {
            "seq": len(self.events) + 1,
            "agent_id": agent_id,
            "from": source,
            "to": destination,
            "reason": reason,
            "initiated_by": initiated_by,
            "temporary": agent["temporary"],
        }
        self.events.append(event)
        agent["history"].append(event)
        return event

    def rebalance(self, demand: Dict[str, int], max_load: int = 4, max_moves: int = 2) -> List[Dict]:
        """Demand-based temporary transfers: if a department's queue per
        worker exceeds ``max_load``, borrow an idle, capable agent from the
        least-loaded department that can spare one. Departments missing from
        ``demand`` are treated as having no pending work."""
        moves: List[Dict] = []

        def load(dept):
            return demand.get(dept, 0) / max(1, len(self.workers.get(dept, [])))

        for _ in range(max_moves):
            hot = [d for d in demand if d in self.workers and load(d) > max_load]
            if not hot:
                break
            target = max(hot, key=load)
            candidates = []
            for agent_id, agent in self.agents.items():
                src = agent["current_department"]
                if (src != target and target in agent["capabilities"] and agent["status"] == "idle"
                        and len(self.workers[src]) > MIN_STAFF and load(src) < max_load):
                    candidates.append((load(src), agent_id))
            if not candidates:
                break
            _, agent_id = min(candidates)
            moves.append(self.transfer(
                agent_id, target,
                reason=f"demand: {demand.get(target, 0)} item(s) for {len(self.workers[target])} worker(s)",
                initiated_by="auto:demand", temporary=True,
            ))
        return moves

    def release_temporary(self) -> List[Dict]:
        """Return agents on temporary (demand-based) assignments to their home department."""
        moves = []
        for agent_id, agent in self.agents.items():
            home = agent["home_department"]
            if agent["temporary"] and agent["current_department"] != home and home in self.workers:
                try:
                    moves.append(self.transfer(agent_id, home, reason="temporary assignment finished",
                                               initiated_by="auto:end_of_shift"))
                except TransferError as exc:
                    LOGGER.warning("Could not return %s home: %s", agent_id, exc)
        return moves

    # --- serialization ----------------------------------------------------
    def report(self) -> Dict:
        return {
            "manager_id": self.manager_id,
            "departments": {name: list(ids) for name, ids in self.workers.items()},
            "assignments": list(self.assignments),
            "agents": {
                agent_id: {k: (list(v) if isinstance(v, list) else v) for k, v in a.items()}
                for agent_id, a in self.agents.items()
            },
            "events": list(self.events),
        }

    def state(self) -> Dict:
        return {
            "manager_id": self.manager_id,
            "departments": {name: list(ids) for name, ids in self.workers.items()},
            "agents": {
                agent_id: {
                    "home_department": a["home_department"],
                    "capabilities": list(a["capabilities"]),
                    "history": list(a["history"])[-20:],
                }
                for agent_id, a in self.agents.items()
            },
        }

    @classmethod
    def from_state(cls, state: Dict) -> "AgentTeam":
        departments = {k: list(v) for k, v in (state.get("departments") or {}).items()}
        agents = state.get("agents") or {}
        team = cls(
            workers=departments,
            manager_id=state.get("manager_id", "manager-1"),
            capabilities={a: list(v.get("capabilities") or []) for a, v in agents.items()} or None,
        )
        for agent_id, saved in agents.items():
            agent = team.agents.get(agent_id)
            if not agent:
                continue
            home = saved.get("home_department")
            if home in team.workers and home in agent["capabilities"]:
                agent["home_department"] = home
            agent["history"] = [h for h in saved.get("history", []) if isinstance(h, dict)]
        return team


def load_team_state(path: Path) -> AgentTeam:
    """Load a persisted roster (user transfers survive between runs). Falls
    back to the default team if the file is missing or invalid."""
    path = Path(path)
    if not path.exists():
        return AgentTeam()
    try:
        team = AgentTeam.from_state(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        LOGGER.warning("Ignoring invalid team state %s: %s", path, exc)
        return AgentTeam()
    for department, ids in DEFAULT_WORKERS.items():
        if department not in team.workers and not any(i in team.agents for i in ids):
            # Older saved rosters predate this department.
            team.workers[department] = list(ids)
            for worker_id in ids:
                team.agents[worker_id] = _new_agent(worker_id, department, default_capabilities(department))
    return team


def save_team_state(team: AgentTeam, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(team.state(), indent=2), encoding="utf-8")
    tmp.replace(path)


def agents_for(team_report: Optional[Dict]) -> Dict[str, Dict]:
    """Agent records from a run's team report; older runs without an
    ``agents`` key get records derived from their department lists."""
    report = team_report or {}
    if isinstance(report.get("agents"), dict) and report["agents"]:
        return report["agents"]
    out = {}
    for department, ids in (report.get("departments") or {}).items():
        for worker_id in ids:
            out[worker_id] = _new_agent(worker_id, department, [department])
    return out


def transfer_events(team_report: Optional[Dict]) -> List[Dict]:
    return [e for e in ((team_report or {}).get("events") or []) if isinstance(e, dict)]
