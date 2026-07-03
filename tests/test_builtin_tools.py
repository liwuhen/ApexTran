from __future__ import annotations

import asyncio
import shlex
import sys

import pytest

import backend.tools.toolimpl as builtin_tools
from backend.core.tools import ToolContext
from backend.llm.messages import build_lc_tools
from backend.tools.shelltool.shell_manager import ShellManager
from backend.tools.toolimpl import bash, bash_output, kill_bash


def _tool_context(tmp_path) -> ToolContext:
    return ToolContext(tape="test-tape", run_id="test-run", state={"_runtime_workspace": str(tmp_path)})


def _python_shell(code: str) -> str:
    return f"{shlex.quote(sys.executable)} -c {shlex.quote(code)}"


@pytest.mark.asyncio
async def test_bash_returns_stdout_for_foreground_command(tmp_path) -> None:
    result = await bash.run(cmd=_python_shell("print('hello')"), context=_tool_context(tmp_path))

    assert result == "hello"


@pytest.mark.asyncio
async def test_foreground_bash_releases_shell_from_shell_manager(tmp_path, monkeypatch) -> None:
    manager = ShellManager()
    monkeypatch.setattr(builtin_tools, "shell_manager", manager)

    result = await bash.run(cmd=_python_shell("print('hello')"), context=_tool_context(tmp_path))

    assert result == "hello"
    assert manager._shells == {}


@pytest.mark.asyncio
async def test_foreground_bash_releases_shell_when_command_fails(tmp_path, monkeypatch) -> None:
    manager = ShellManager()
    monkeypatch.setattr(builtin_tools, "shell_manager", manager)

    with pytest.raises(RuntimeError, match="command exited with code"):
        await bash.run(cmd=_python_shell("import sys; sys.exit(2)"), context=_tool_context(tmp_path))

    assert manager._shells == {}


@pytest.mark.asyncio
async def test_bash_non_zero_exit_is_returned_as_tool_error(tmp_path) -> None:
    """Through the LangGraph tool path a failing tool returns its error as text."""
    command = _python_shell("import sys; print('boom'); sys.exit(7)")
    bash_tool = next(t for t in build_lc_tools([bash], _tool_context(tmp_path)) if t.name == "bash")

    result = await bash_tool.ainvoke({"cmd": command})

    assert "error:" in result
    assert "command exited with code 7" in result
    assert "boom" in result


@pytest.mark.asyncio
async def test_background_bash_exposes_output_via_bash_output(tmp_path) -> None:
    command = _python_shell(
        "import sys, time; print('start'); sys.stdout.flush(); time.sleep(0.2); print('done'); sys.stdout.flush()"
    )

    started = await bash.run(cmd=command, background=True, context=_tool_context(tmp_path))
    shell_id = started.removeprefix("started: ").strip()

    await asyncio.sleep(0.35)
    output = await bash_output.run(shell_id=shell_id)

    assert output.startswith(f"id: {shell_id}\nstatus: exited\n")
    assert "exit_code: 0" in output
    assert "start" in output
    assert "done" in output


@pytest.mark.asyncio
async def test_kill_bash_terminates_background_process_and_releases_shell(tmp_path) -> None:
    started = await bash.run(
        cmd=_python_shell("import time; time.sleep(10)"),
        background=True,
        context=_tool_context(tmp_path),
    )
    shell_id = started.removeprefix("started: ").strip()

    killed = await kill_bash.run(shell_id=shell_id)

    assert killed.startswith(f"id: {shell_id}\nstatus: exited\nexit_code: ")
    assert "exit_code: null" not in killed
    with pytest.raises(KeyError, match="unknown shell id"):
        await bash_output.run(shell_id=shell_id)


@pytest.mark.asyncio
async def test_kill_bash_returns_status_when_process_already_finished(tmp_path) -> None:
    started = await bash.run(
        cmd=_python_shell("print('done')"),
        background=True,
        context=_tool_context(tmp_path),
    )
    shell_id = started.removeprefix("started: ").strip()

    await asyncio.sleep(0.1)
    result = await kill_bash.run(shell_id=shell_id)

    assert result == f"id: {shell_id}\nstatus: exited\nexit_code: 0"
