import pytest
from pydantic import ValidationError

from app.routes.pine import ScriptIn

V5 = '//@version=5\nindicator("x")\nplot(close)\n'


def test_valid_script() -> None:
    s = ScriptIn(name="  My   RSI ", source=V5.replace("\n", "\r\n"))
    assert s.name == "My RSI" and "\r" not in s.source
    assert ScriptIn(name="x", source=V5.replace("5", "6", 1)).source.startswith("//@version=6")


@pytest.mark.parametrize(
    ("name", "source"),
    [
        ("", V5),
        ("x" * 81, V5),
        ("ok", '//@version=4\nstudy("x")\nplot(close)'),
        ("ok", 'indicator("no version")\nplot(close)'),
        ("ok", V5 + "\x00"),
        ("ok", V5 + "x" * 100_001),
    ],
)
def test_invalid_scripts(name: str, source: str) -> None:
    with pytest.raises(ValidationError):
        ScriptIn(name=name, source=source)
