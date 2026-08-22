"""
Unit tests for assistant.charts.LazyFigure -- confirms the expensive build
function is not called until something actually uses the figure, and that
once resolved it behaves like the real object for every operation callers
perform on it (chat_cli.py, discord_bot.py, whatsapp_bot.py).
"""
import pytest

from assistant.charts import LazyFigure


class _FakeFigure:
    def __init__(self, label):
        self.label = label
        self.html_written_to = None

    def write_html(self, path):
        self.html_written_to = path

    def write_image(self, path):
        pass


def test_build_fn_not_called_until_accessed():
    calls = []

    def build():
        calls.append(1)
        return _FakeFigure("built")

    lazy = LazyFigure(build)
    assert calls == []  # not built yet just from construction
    lazy.write_html("out.html")
    assert calls == [1]


def test_build_fn_called_only_once_even_with_multiple_accesses():
    calls = []

    def build():
        calls.append(1)
        return _FakeFigure("built")

    lazy = LazyFigure(build)
    lazy.label  # first access resolves
    lazy.write_html("out.html")  # second access should reuse
    assert calls == [1]


def test_args_and_kwargs_forwarded():
    seen = {}

    def build(a, b, c=None):
        seen["args"] = (a, b, c)
        return _FakeFigure("x")

    lazy = LazyFigure(build, 1, 2, c=3)
    lazy.label
    assert seen["args"] == (1, 2, 3)


def test_is_not_none_and_truthy():
    lazy = LazyFigure(lambda: _FakeFigure("x"))
    assert lazy is not None
    assert bool(lazy) is True


def test_never_accessed_means_never_built():
    # Simulates the web app / Discord / WhatsApp path where result["chart"]
    # exists in the dict but is never read because image_path is used
    # instead.
    calls = []

    def build():
        calls.append(1)
        return _FakeFigure("x")

    result = {"chart": LazyFigure(build), "image_path": "/tmp/fake.png"}
    # caller only reads image_path, never touches chart
    _ = result["image_path"]
    assert calls == []
