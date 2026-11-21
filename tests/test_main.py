"""Tests for the command line runner."""

import sys

import pytest

import src.main as main_module


@pytest.fixture(autouse=True)
def skip_log_file(monkeypatch):
    """Keep the tests from writing to logs/vibefinder.log."""
    monkeypatch.setattr(main_module, "configure_logging", lambda **options: None)


def run_cli(monkeypatch, capsys, *command_line_arguments) -> str:
    """Run main() with the given arguments and return what it printed."""
    monkeypatch.setattr(sys, "argv", ["src.main", *command_line_arguments])
    main_module.main()
    return capsys.readouterr().out


def test_ask_prints_recommendations(monkeypatch, capsys):
    output_text = run_cli(monkeypatch, capsys, "--ask", "chill lofi for studying", "--k", "2")

    assert "Status: answered" in output_text
    assert "lofi / chill" in output_text
    assert "Confidence:" in output_text


def test_ask_with_trace_shows_the_pipeline_steps(monkeypatch, capsys):
    output_text = run_cli(monkeypatch, capsys, "--ask", "k-pop", "--trace")

    assert "Trace:" in output_text
    assert "REVISE:" in output_text


def test_ask_with_an_empty_request_is_rejected(monkeypatch, capsys):
    output_text = run_cli(monkeypatch, capsys, "--ask", "")

    assert "Status: rejected" in output_text


def test_chat_mode_answers_until_quit(monkeypatch, capsys):
    typed_lines = iter(["jazz", "quit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(typed_lines))

    output_text = run_cli(monkeypatch, capsys, "--chat", "--k", "1")

    assert "Coffee Shop Stories" in output_text
    assert "Goodbye." in output_text


def test_profile_mode_still_works(monkeypatch, capsys):
    output_text = run_cli(monkeypatch, capsys, "--profile", "chill_lofi", "--k", "1")

    assert "Profile: Chill Lofi" in output_text
    assert "Library Rain" in output_text


def test_profile_mode_warns_about_out_of_range_targets(monkeypatch, capsys):
    output_text = run_cli(monkeypatch, capsys, "--profile", "out_of_range_energy", "--k", "1")

    assert "Warning: energy=1.5 is outside 0-1" in output_text


def test_profile_mode_warns_about_an_empty_profile(monkeypatch, capsys):
    output_text = run_cli(monkeypatch, capsys, "--profile", "no_preferences", "--k", "1")

    assert "not personalized" in output_text


def test_list_shows_profiles_and_modes(monkeypatch, capsys):
    output_text = run_cli(monkeypatch, capsys, "--list")

    assert "chill_lofi" in output_text
    assert "mood_first" in output_text
