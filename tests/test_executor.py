"""Tests for command parsing, validation and execution dispatch."""

from __future__ import annotations

import pytest

from hotstring3.executor import (
    CommandExecutor,
    ParsedCommand,
    parse_command,
    powershell_argv,
    validate_command,
)
from hotstring3.powershell import PowerShellInfo


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "kind", "payload"),
    [
        ("tHello", "type", "Hello"),
        ("t Hello", "type", "Hello"),
        ("t:Hello", "type", "Hello"),
        ("t: Hello", "type", " Hello"),
        ("sStart-Process notepad", "powershell", "Start-Process notepad"),
        ("s:Get-Date", "powershell", "Get-Date"),
        ("aopen", "action", "open"),
        ("a:open", "action", "open"),
        ("rStart-Process notepad", "startup", "Start-Process notepad"),
        ("tสวัสดีครับ", "type", "สวัสดีครับ"),
        ("tLine one\nLine two", "type", "Line one\nLine two"),
        ("  tHello  ", "type", "Hello"),
    ],
)
def test_parse_command(raw: str, kind: str, payload: str) -> None:
    parsed = parse_command(raw)
    assert parsed == ParsedCommand(kind=kind, payload=payload, raw=raw)  # type: ignore[arg-type]


def test_parse_strips_only_one_separator() -> None:
    assert parse_command("t  two spaces").payload == " two spaces"
    assert parse_command("t::colons").payload == ":colons"


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "xHello", "Hello", "t", "t ", "s", "s:", "a", "a:", "r", ":", "5hello"],
)
def test_invalid_commands(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_command(raw)


def test_prefix_is_lowercase_only() -> None:
    with pytest.raises(ValueError):
        parse_command("THello")
    with pytest.raises(ValueError):
        parse_command("SOpen-Notepad")


def test_parse_rejects_non_string() -> None:
    with pytest.raises(ValueError):
        parse_command(None)  # type: ignore[arg-type]


def test_validate_command_returns_parsed() -> None:
    assert validate_command("aopen").kind == "action"


def test_powershell_argv_contains_required_flags() -> None:
    argv = powershell_argv("Get-Date")
    assert argv[0] == "powershell.exe"
    assert "-NoProfile" in argv
    assert "-WindowStyle" in argv and "Hidden" in argv
    assert "-ExecutionPolicy" in argv and "Bypass" in argv
    assert argv[-2:] == ["-Command", "Get-Date"]


def test_powershell_argv_accepts_detected_executable() -> None:
    argv = powershell_argv("Get-Date", r"C:\Program Files\PowerShell\7\pwsh.exe")
    assert argv[0].endswith("pwsh.exe")


def test_powershell_status_text_matches_ui_format() -> None:
    assert PowerShellInfo(r"C:\PowerShell\7\pwsh.exe", "7.4.2").status_text() == (
        "PowerShell: 7.4.2 (pwsh)"
    )
    assert PowerShellInfo("powershell.exe", "5.1.22621.1").status_text() == (
        "PowerShell: 5.1.22621.1"
    )
    assert PowerShellInfo("powershell.exe", "").status_text() == "PowerShell: not detected"


# ---------------------------------------------------------------------------
# Execution dispatch
# ---------------------------------------------------------------------------


def make_executor(**kwargs):
    typed: list[str] = []
    scripts: list[str] = []
    errors: list[str] = []
    opened: list[bool] = []

    executor = CommandExecutor(
        typing_handler=typed.append,
        powershell_handler=scripts.append,
        on_error=errors.append,
        open_ui=lambda: opened.append(True),
        **kwargs,
    )
    return executor, typed, scripts, errors, opened


def test_execute_types_text() -> None:
    executor, typed, scripts, errors, opened = make_executor()
    assert executor.execute("tHello") is True
    assert typed == ["Hello"]
    assert scripts == [] and errors == [] and opened == []


def test_execute_unicode_text() -> None:
    executor, typed, *_ = make_executor()
    executor.execute("t:สวัสดี\nขอบคุณ")
    assert typed == ["สวัสดี\nขอบคุณ"]


def test_execute_powershell() -> None:
    executor, typed, scripts, errors, _ = make_executor()
    assert executor.execute("sStart-Process notepad") is True
    assert scripts == ["Start-Process notepad"]
    assert typed == [] and errors == []


def test_execute_startup_command() -> None:
    executor, _typed, scripts, _errors, _ = make_executor()
    executor.execute("rGet-Date")
    assert scripts == ["Get-Date"]


def test_execute_action_open() -> None:
    executor, _typed, _scripts, errors, opened = make_executor()
    assert executor.execute("aopen") is True
    assert opened == [True]
    assert errors == []


def test_execute_unknown_action_reports_error() -> None:
    executor, _typed, _scripts, errors, opened = make_executor()
    assert executor.execute("afrobnicate") is False
    assert opened == []
    assert len(errors) == 1
    assert "Unknown internal action" in errors[0]


def test_invalid_command_never_raises() -> None:
    executor, typed, scripts, errors, opened = make_executor()
    assert executor.execute("nonsense") is False
    assert typed == [] and scripts == [] and opened == []
    assert errors and "valid prefix" in errors[0]


def test_handler_exception_is_caught_and_reported() -> None:
    errors: list[str] = []

    def explode(_text: str) -> None:
        raise RuntimeError("boom")

    executor = CommandExecutor(typing_handler=explode, on_error=errors.append)
    assert executor.execute("tHello") is False
    assert errors and "boom" in errors[0]


def test_error_callback_failure_is_swallowed() -> None:
    def bad_callback(_message: str) -> None:
        raise RuntimeError("callback broke")

    executor = CommandExecutor(typing_handler=lambda _text: None, on_error=bad_callback)
    assert executor.execute("tHello") is True


def test_action_without_ui_handler_reports_error() -> None:
    errors: list[str] = []
    executor = CommandExecutor(on_error=errors.append)
    assert executor.execute("aopen") is False
    assert errors and "No UI handler" in errors[0]


def test_execute_async_runs_handler() -> None:
    executor, typed, *_ = make_executor()
    thread = executor.execute_async("tAsync")
    thread.join(timeout=2)
    assert typed == ["Async"]


def test_run_startup_commands_runs_only_r_commands() -> None:
    executor, _typed, scripts, errors, _opened = make_executor()
    executor.run_startup_commands(
        [
            "rStart-Process notepad",
            "tHello",
            "sGet-Date",
            "invalid",
        ]
    )
    assert scripts == ["Start-Process notepad"]
    assert errors == []
