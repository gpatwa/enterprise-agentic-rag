from app.harness import GradeCase, grade_case, render_json, render_junit, render_markdown, write_report_artifacts


def report():
    return grade_case(GradeCase(case_id="case-1", suite_version="suite-1", trace_valid=True))


def test_report_renderers_identify_case_stage_and_version(tmp_path):
    current = report()
    json_report = render_json(current)
    junit_report = render_junit(current)
    markdown_report = render_markdown(current)
    assert '"case_id": "case-1"' in json_report
    assert 'name="trace"' in junit_report
    assert "`retrieval`" in markdown_report
    paths = write_report_artifacts(current, tmp_path)
    assert set(paths) == {"json", "junit", "markdown"}
    assert all(path.exists() for path in paths.values())
