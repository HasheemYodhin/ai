import asyncio
import json

import pytest

from dabba.cli.agent_proxy import AgentProxy
from dabba.cli.config import CliConfig
from dabba.cli.tui import DabbaTUI

pytest.importorskip("textual")


def test_save_command_writes_checkpoint_without_crashing(tmp_path):
    """
    Regression test: /save used to read self.agent._agent_loop.context, an
    attribute AgentLoop has never had (the real one is context_manager) —
    always raised AttributeError, silently caught and reported as
    "Save failed: ...". Fixed to use AgentProxy.checkpoint_context().
    """

    async def run():
        config = CliConfig()
        config.history_file = str(tmp_path / "history.jsonl")
        agent = AgentProxy(cli_config=config)
        loop = agent._ensure_agent_loop(str(tmp_path), fresh_session=True)
        loop.llm_generate = lambda messages, params: "a reply"
        await loop.chat("hello there")

        app = DabbaTUI(agent=agent, config=config, version="1.0")
        posted = []
        async with app.run_test() as pilot:
            await pilot.pause()
            app._post_system = lambda text: posted.append(text)
            save_path = str(tmp_path / "manual_save.jsonl")
            app._cmd_save([save_path])
            await pilot.pause()
            return posted, save_path

    posted, save_path = asyncio.run(run())

    assert len(posted) == 1
    assert "Save failed" not in posted[0]
    assert "Saved" in posted[0]

    lines = [json.loads(line) for line in open(save_path) if line.strip()]
    assert any(entry.get("content") == "hello there" for entry in lines)
    assert any(entry.get("__checkpoint__") for entry in lines)
