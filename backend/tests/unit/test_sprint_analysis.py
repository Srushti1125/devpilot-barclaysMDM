from app.services.sprint_analysis import analyze_sprint_plan


def test_sprint_analysis_finds_longest_dependency_path_and_velocity():
    result = analyze_sprint_plan({"items": [
        {"story_title": "A", "story_points": 3, "effort_estimate_hours": 4, "dependencies": [], "sprint": 1},
        {"story_title": "B", "story_points": 5, "effort_estimate_hours": 6, "dependencies": ["A"], "sprint": 2},
        {"story_title": "C", "story_points": 8, "effort_estimate_hours": 2, "dependencies": ["A"], "sprint": 2},
        {"story_title": "D", "story_points": 2, "effort_estimate_hours": 3, "dependencies": ["B", "C"], "sprint": 3},
    ]})
    assert result["critical_path"] == ["A", "B", "D"]
    assert result["critical_path_effort_hours"] == 13
    assert result["estimated_velocity_required"] == 6
    assert result["total_story_points"] == 18
    assert result["has_dependency_cycle"] is False


def test_sprint_analysis_reports_missing_dependencies_and_cycles():
    result = analyze_sprint_plan({"items": [
        {"story_title": "A", "dependencies": ["B", "Not in plan"]},
        {"story_title": "B", "dependencies": ["A"]},
    ]})
    assert result["missing_dependencies"] == ["Not in plan"]
    assert result["has_dependency_cycle"] is True
