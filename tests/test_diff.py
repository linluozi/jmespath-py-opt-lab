#!/usr/bin/env python3
"""Differential test: patched Lexer vs the pre-patch _consume_until.

The optimized method is compared against a subclass that restores the exact
upstream implementation of Lexer._consume_until.  For every generated
expression both lexers must produce a byte-identical serialization of the
full token stream (type, value, start, end), or the same exception class and
message.  No tolerance, no approximate comparison.

Run directly (stdlib only):
    PYTHONPATH=/path/to/patched-jmespath python3 tests/test_diff.py

or under pytest:
    PYTHONPATH=/path/to/patched-jmespath python3 -m pytest tests/test_diff.py -q
"""
import json
import random
import sys

from jmespath.exceptions import LexerError
from jmespath.lexer import Lexer

SEED = 20261031
RANDOM_CASES = 1200


class BaselineLexer(Lexer):
    """Lexer with the verbatim pre-patch _consume_until implementation."""

    def _consume_until(self, delimiter):
        # Consume until the delimiter is reached,
        # allowing for the delimiter to be escaped with "\".
        start = self._position
        buff = ''
        self._next()
        while self._current != delimiter:
            if self._current == '\\':
                buff += '\\'
                self._next()
            if self._current is None:
                # We're at the EOF.
                raise LexerError(lexer_position=start,
                                 lexer_value=self._expression[start:],
                                 message="Unclosed %s delimiter" % delimiter)
            buff += self._current
            self._next()
        # Skip the closing delimiter.
        self._next()
        return buff


def serialize(lexer_cls, expression):
    """Full token stream (or exception) as canonical UTF-8 bytes."""
    try:
        tokens = list(lexer_cls().tokenize(expression))
    except Exception as exc:  # noqa: BLE001 - exceptions are part of the contract
        payload = ["exception", type(exc).__name__, str(exc)]
        return b"err:" + json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return b"ok:" + json.dumps(tokens, ensure_ascii=False, sort_keys=True).encode("utf-8")


def build_cases():
    rnd = random.Random(SEED)
    alphabet = list("abcXYZ_09 .[]*|&!<>=@(){},\":'`\\\n\t\u00e9\u4e2d\U0001F600")
    cases = []
    for _ in range(RANDOM_CASES):
        length = rnd.randrange(0, 80)
        cases.append("".join(rnd.choice(alphabet) for _ in range(length)))
    edge = [
        "",
        "a",
        " ",
        "'abc'",
        "''",
        '"abc"',
        '""',
        "`1`",
        "``",
        "'a\\'b'",
        '"a\\"b"',
        "`a\\`b`",
        "'\\\\'",
        "'a\\\\'",
        "'\\",
        '"\\',
        "`\\",
        "'unterminated",
        '"unterminated',
        "`unterminated",
        "'" + "x" * 5000 + "'",
        '"' + "\u4e2d" * 5000 + '"',
        "`" + "9" * 5000 + "`",
        "foo.bar[?baz > `10`].qux[*].name",
        "'" + "\U0001F600" * 100 + "'",
        "`NaN`",
        "`Infinity`",
        "'line\nbreak'",
        "foo || bar && baz",
    ]
    return cases + edge


def test_differential():
    cases = build_cases()
    diffs = []
    for expression in cases:
        baseline = serialize(BaselineLexer, expression)
        optimized = serialize(Lexer, expression)
        if baseline != optimized:
            diffs.append((expression, baseline, optimized))
    assert len(cases) >= 1000, len(cases)
    assert not diffs, "%d/%d cases differ; first: %r\nbaseline=%r\noptimized=%r" % (
        len(diffs), len(cases), diffs[0][0][:120], diffs[0][1][:400], diffs[0][2][:400])
    print("differential cases: %d, byte-identical: %d, diffs: 0" % (len(cases), len(cases)))


if __name__ == "__main__":
    test_differential()
    sys.exit(0)
