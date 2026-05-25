from hermes_dreaming import __version__
from hermes_dreaming.cli import main


def test_version() -> None:
    assert __version__ == "0.1.0"


def test_status_command(capsys) -> None:
    assert main(["status"]) == 0
    out = capsys.readouterr().out.strip()
    assert "dream" in out.lower()
