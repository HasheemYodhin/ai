from dabba.cli.session import InteractiveSession
from dabba.cli.agent_proxy import AgentProxy
from dabba.cli.permissions import PermissionManager
from dabba.cli.output_handler import OutputHandler
from dabba.cli.config import CliConfig


def _dummy_llm_generate(messages, params):
    return "OK, doing that."


def _make_session(tmp_path):
    config = CliConfig()
    config.history_file = str(tmp_path / "history.jsonl")
    output = OutputHandler(config=config, no_color=True)
    permissions = PermissionManager(mode="ask", persistent=False)
    agent = AgentProxy(cli_config=config, output=output, permissions=permissions)
    return InteractiveSession(
        agent=agent, output=output, config=config, permissions=permissions
    )


def test_checkpoint_restores_full_agent_state(tmp_path):
    session = _make_session(tmp_path)
    loop = session.agent._ensure_agent_loop(str(tmp_path))
    loop.llm_generate = _dummy_llm_generate
    loop.run("Please help me build something")
    session.permissions.grant_session("shell_exec")
    session.permissions.set_mode("allow")
    session.history.append(
        {"role": "user", "content": "Please help me build something"}
    )
    session.history.append({"role": "assistant", "content": "OK, doing that."})

    save_path = str(tmp_path / "checkpoint.jsonl")
    session._save_history(save_path, quiet=True)

    fresh = _make_session(tmp_path)
    assert fresh.permissions.mode == "ask"
    fresh._load_history(save_path)

    assert fresh.permissions.mode == "allow"
    assert "shell_exec" in fresh.permissions._session_allowed
    assert len(fresh.history) == 2
    restored = fresh.agent._agent_loop.context_manager.get_messages()
    assert any("build something" in m["content"] for m in restored)
    assert any(m["content"] == "OK, doing that." for m in restored)


def test_old_format_history_file_still_loads_without_checkpoint(tmp_path):
    old_format_path = tmp_path / "old.jsonl"
    old_format_path.write_text(
        '{"role": "user", "content": "hi"}\n{"role": "assistant", "content": "hello"}\n'
    )
    session = _make_session(tmp_path)
    session._load_history(str(old_format_path))
    assert len(session.history) == 2
    assert session.agent._agent_loop is None
