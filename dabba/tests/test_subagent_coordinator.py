import pytest

from dabba.platform.coding import (
    SchemaValidationError,
    SubagentCoordinator,
    validate_json_schema,
)


def test_run_fans_out_in_parallel_and_isolates_failures():
    coordinator = SubagentCoordinator()

    def runner(role, prompt):
        if role == "broken":
            raise RuntimeError("boom")
        return f"{role} handled: {prompt}"

    results = coordinator.run(
        {"reviewer": "check auth.py", "writer": "add tests", "broken": "x"},
        runner,
    )
    assert results["reviewer"] == {
        "success": True,
        "result": "reviewer handled: check auth.py",
    }
    assert results["writer"] == {"success": True, "result": "writer handled: add tests"}
    assert results["broken"] == {"success": False, "error": "boom"}


def test_pipeline_chains_stage_output_into_the_next_prompt():
    coordinator = SubagentCoordinator()
    seen_prompts = []

    def runner(role, prompt):
        seen_prompts.append((role, prompt))
        return f"[{role}]{prompt}"

    stages = [
        {"role": "draft", "prompt_template": "write about: {input}"},
        {"role": "edit", "prompt_template": "polish this: {input}"},
    ]
    results = coordinator.pipeline(stages, runner, initial_input="dabba release notes")

    assert seen_prompts[0] == ("draft", "write about: dabba release notes")
    assert seen_prompts[1] == (
        "edit",
        "polish this: [draft]write about: dabba release notes",
    )
    assert results[0]["success"] and results[1]["success"]
    assert (
        results[1]["result"]
        == "[edit]polish this: [draft]write about: dabba release notes"
    )


def test_pipeline_stops_at_a_broken_stage_and_does_not_run_the_rest():
    coordinator = SubagentCoordinator()
    calls = []

    def runner(role, prompt):
        calls.append(role)
        if role == "middle":
            raise RuntimeError("stage failed")
        return "ok"

    stages = [
        {"role": "first", "prompt_template": "{input}"},
        {"role": "middle", "prompt_template": "{input}"},
        {"role": "last", "prompt_template": "{input}"},
    ]
    results = coordinator.pipeline(stages, runner)

    assert calls == ["first", "middle"]  # "last" never runs
    assert [r["role"] for r in results] == ["first", "middle"]
    assert results[1]["success"] is False
    assert "stage failed" in results[1]["error"]


def test_pipeline_validates_structured_output_against_schema():
    coordinator = SubagentCoordinator()
    schema = {
        "type": "object",
        "required": ["bugs"],
        "properties": {"bugs": {"type": "array", "items": {"type": "string"}}},
    }

    def good_runner(role, prompt):
        return '{"bugs": ["off-by-one in loop", "missing null check"]}'

    results = coordinator.pipeline(
        [{"role": "finder", "prompt_template": "{input}", "output_schema": schema}],
        good_runner,
        initial_input="scan the repo",
    )
    assert results[0]["success"] is True
    assert results[0]["result"] == {
        "bugs": ["off-by-one in loop", "missing null check"]
    }

    def bad_runner(role, prompt):
        return '{"wrong_key": []}'

    results = coordinator.pipeline(
        [{"role": "finder", "prompt_template": "{input}", "output_schema": schema}],
        bad_runner,
    )
    assert results[0]["success"] is False
    assert "bugs" in results[0]["error"]


def test_validate_json_schema_directly():
    validate_json_schema(
        {"name": "x", "count": 3},
        {
            "type": "object",
            "required": ["name"],
            "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
        },
    )
    with pytest.raises(SchemaValidationError):
        validate_json_schema(
            {"count": "not a number"},
            {
                "type": "object",
                "required": ["name"],
                "properties": {"count": {"type": "integer"}},
            },
        )
