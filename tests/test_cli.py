from pathlib import Path

import pytest

from map_maker.cli import main


def test_root_help_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "terrain" in capsys.readouterr().out


def test_terrain_help_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["terrain"]) == 0
    output = capsys.readouterr().out
    assert "Build and inspect deterministic terrain projects" in output
    assert "gui" in output


def test_terrain_gui_help_is_available(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["terrain", "gui", "--help"])

    assert exit_info.value.code == 0
    assert "closed SVG land shapes" in " ".join(capsys.readouterr().out.split())


def test_gui_accepts_a_startup_project(monkeypatch: pytest.MonkeyPatch) -> None:
    from map_maker.terrain import ui
    opened: list[Path | None] = []
    def run(project: Path | None = None) -> None:
        opened.append(project)
    monkeypatch.setattr(ui, "run", run)
    assert main(["terrain", "gui", "--project", "example.terrain.json"]) == 0
    assert opened == [Path("example.terrain.json")]
