"""Dependency and critical path analysis for generated sprint plans."""
from __future__ import annotations


def analyze_sprint_plan(content: dict) -> dict:
    items = content.get("items", [])
    by_title = {item.get("story_title"): item for item in items if item.get("story_title")}
    dependencies = {
        title: [dep for dep in item.get("dependencies", []) if dep in by_title]
        for title, item in by_title.items()
    }
    missing = sorted({dep for item in items for dep in item.get("dependencies", [])
                      if dep not in by_title})
    visiting: set[str] = set()
    visited: set[str] = set()
    best: dict[str, tuple[float, list[str]]] = {}
    cycle = False

    def longest(title: str) -> tuple[float, list[str]]:
        nonlocal cycle
        if title in visiting:
            cycle = True
            return 0.0, []
        if title in visited:
            return best[title]
        visiting.add(title)
        parent_duration, parent_path = 0.0, []
        for dep in dependencies[title]:
            duration, path = longest(dep)
            if duration > parent_duration:
                parent_duration, parent_path = duration, path
        visiting.remove(title)
        visited.add(title)
        duration = max(0.0, float(by_title[title].get("effort_estimate_hours", 0) or 0))
        best[title] = (parent_duration + duration, parent_path + [title])
        return best[title]

    for title in by_title:
        longest(title)
    critical_hours, critical_path = max(best.values(), default=(0.0, []), key=lambda pair: pair[0])
    total_points = sum(max(0, int(item.get("story_points", 0) or 0)) for item in items)
    sprint_count = max((int(item.get("sprint", 0) or 0) for item in items), default=0)
    inbound: dict[str, int] = {title: 0 for title in by_title}
    for deps in dependencies.values():
        for dep in deps:
            inbound[dep] += 1
    return {
        "critical_path": critical_path,
        "critical_path_effort_hours": round(critical_hours, 2),
        "estimated_velocity_required": round(total_points / sprint_count, 2) if sprint_count else None,
        "total_story_points": total_points,
        "planned_sprints": sprint_count,
        "bottlenecks": sorted(title for title, count in inbound.items() if count >= 3),
        "missing_dependencies": missing,
        "has_dependency_cycle": cycle,
    }
