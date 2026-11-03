"""Group pending requests that come from one task, so the user answers once.

Requests group when the same app asked them within a few minutes for one task (tasks.py),
or for the same or a very similar question. Requests for passwords and login codes never
group: those are always answered one at a time.
"""

from . import similar

WINDOW_S = 600
SAME_TASK = 0.6


def same_task(a: str, b: str) -> bool:
    if " ".join(a.lower().split()) == " ".join(b.lower().split()):
        return True
    best = similar.rank(a, [b], 1)
    return bool(best) and best[0][1] >= SAME_TASK


def stands_alone(grant: dict) -> bool:
    return grant.get("category") == "security"


def together(a: dict, b: dict) -> bool:
    if a["agent_id"] != b["agent_id"]:
        return False
    return bool(a.get("task_id") and a.get("task_id") == b.get("task_id")) or same_task(a["user_request"], b["user_request"])


def group(pending: list[dict]) -> list[list[dict]]:
    """Each group oldest first; groups newest first."""
    groups: list[list[dict]] = []
    for g in sorted(pending, key=lambda g: g["created_at"]):
        home = None
        if not stands_alone(g):
            home = next(
                (
                    grp
                    for grp in groups
                    if not stands_alone(grp[0])
                    and g["created_at"] - grp[-1]["created_at"] <= WINDOW_S
                    and any(together(m, g) for m in grp)
                ),
                None,
            )
        if home is not None:
            home.append(g)
        else:
            groups.append([g])
    return sorted(groups, key=lambda grp: grp[-1]["created_at"], reverse=True)


def group_of(grant_id: str, pending: list[dict]) -> list[dict]:
    return next((grp for grp in group(pending) if any(g["id"] == grant_id for g in grp)), [])
