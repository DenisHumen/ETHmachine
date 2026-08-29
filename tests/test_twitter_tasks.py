"""Twitter-задачи: порядок аргументов и имя модуля.

Комментарий в X отправляется методом ``Twitter.comment(text, tweet_id)``.
Раньше раннер звал его позиционно как ``comment(tweet_id, comment_text)``,
и API получал ID твита в качестве текста ответа. Ошибка молчаливая —
сеть не трогается, поэтому ловим её тестом на фейковом клиенте.
"""

from __future__ import annotations

import ast
import asyncio

import pytest

from tests.conftest import PROJECT_ROOT


class _FakeTwitterClient:
    """Заглушка клиента: запоминает, с чем позвали ``comment``."""

    def __init__(self):
        self.calls: list[tuple[tuple, dict]] = []

    async def comment(self, text: str, tweet_id: str, media_base64=None):
        self.calls.append(((text, tweet_id), {"media_base64": media_base64}))
        return True


@pytest.fixture()
def runner(tmp_project):
    # Раннер в конструкторе поднимает SQLite — держим её во временном каталоге.
    from modules.twitter.twitter_task_runner import TwitterTaskRunner

    return TwitterTaskRunner()


def test_comment_gets_text_and_tweet_id_in_right_slots(runner):
    """Текст комментария не должен подменяться ID твита."""
    client = _FakeTwitterClient()
    task = {
        "type": "comment",
        "link": "https://x.com/someone/status/1234567890",
        "value": "Отличный пост!",
    }

    ok, _message = asyncio.run(runner.execute_task(client, task))

    assert ok is True
    (text, tweet_id), _kwargs = client.calls[0]
    assert text == "Отличный пост!"
    assert tweet_id == "1234567890"


def test_comment_falls_back_to_default_text(runner):
    """Пустое value подставляет дефолтный текст, а не ID твита."""
    client = _FakeTwitterClient()
    task = {"type": "comment", "link": "1234567890", "value": ""}

    asyncio.run(runner.execute_task(client, task))

    (text, tweet_id), _kwargs = client.calls[0]
    assert tweet_id == "1234567890"
    assert text and not text.isdigit()


def test_comment_signature_keeps_text_first():
    """Сигнатура ``comment`` — контракт для раннера, фиксируем порядок.

    Метод обёрнут декоратором ``retry_async`` без ``functools.wraps``,
    поэтому реальные имена параметров читаем из AST, а не из inspect.
    """
    source = (PROJECT_ROOT / "modules" / "twitter" / "twitter_task.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    comment_defs = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "comment"
    ]
    assert len(comment_defs) == 1, "ожидали ровно один метод comment"
    params = [arg.arg for arg in comment_defs[0].args.args]
    assert params[:3] == ["self", "text", "tweet_id"]


def test_no_misspelled_twitter_module():
    """Файл модуля называется twitter_task.py — опечатка «tiwtter» не вернулась."""
    assert (PROJECT_ROOT / "modules" / "twitter" / "twitter_task.py").exists()
    assert not (PROJECT_ROOT / "modules" / "twitter" / "tiwtter_task.py").exists()

    typo = "ti" + "wtter"  # склеиваем, чтобы сам тест не попал в выборку
    offenders = [
        str(path.relative_to(PROJECT_ROOT))
        for path in PROJECT_ROOT.rglob("*.py")
        if "__pycache__" not in path.parts
        and "tests" not in path.relative_to(PROJECT_ROOT).parts
        and typo in path.read_text(encoding="utf-8")
    ]
    assert not offenders, f"остались ссылки на опечатку: {offenders}"
