# jmespath-py-opt-lab

`jmespath.py` is the reference Python implementation of the JMESPath query language; this lab replaces the character-by-character loop in `Lexer._consume_until` with `str.find` + slice chunking, making uncached parsing of long string literals **50.4x** faster at the median scale (61.4x at 128 KB) with byte-identical output.

Upstream: https://github.com/jmespath/jmespath.py

## Result

Uncached parse of a single raw-string literal (`'<payload>'`), median of 5 timed runs after 3 warmups, `time.perf_counter()`, seed `20261031`.

| Scale | Payload | Baseline median | Optimized median | Speedup |
| --- | ---: | ---: | ---: | ---: |
| small | 8,192 B | 1.942 ms | 0.041 ms | **47.04x** |
| medium | 32,768 B | 7.742 ms | 0.154 ms | **50.36x** |
| large | 131,072 B | 30.878 ms | 0.503 ms | **61.43x** |

Median speedup across the three scales: **50.36x**. The gain comes from one function, `jmespath/lexer.py::Lexer._consume_until` (32 insertions, 10 deletions): the old code called `self._next()` and appended one character at a time; the new code locates the next delimiter/backslash with `str.find`, copies the whole run as one slice, and joins the chunks. For a 128 KB literal that removes ~131k Python-level loop iterations. The change only touches quoted identifiers, raw strings and backtick literals; no other token type or public API is modified.

Relative standard deviation was 1.1% / 0.3% / 0.4% for the baseline and 9.2% / 13.5% / 8.0% for the optimized build. The optimized medium scale (13.5%) exceeds 10% because each sample is only ~0.15 ms, close to timer and scheduler granularity, with 5 samples per scale; raw samples are kept in `benchmark/raw/`.

## Correctness

Differential test: **1229 cases, 1229 byte-identical, 0 differences**. The test compares the full token stream (type, value, start, end) serialized as canonical UTF-8 JSON, plus exception class and message for invalid input. Cases are 1200 seeded random expressions over an alphabet including quotes, backticks, backslashes, newlines, non-ASCII (`é`, `中`) and emoji, plus 29 boundary cases (empty, single char, unterminated strings, trailing backslash, escaped delimiters, 5000-char literals, `NaN`/`Infinity` literals).

```
PYTHONPATH=/tmp/jm python3 tests/test_diff.py
# differential cases: 1229, byte-identical: 1229, diffs: 0
```

## Quality gates

| Gate | Result | Reproduce |
| --- | --- | --- |
| G1 upstream tests green | 991 passed, 1 skipped (1.06 s) after patch; identical 991 passed, 1 skipped (1.09 s) before | `cd /tmp/jm && /tmp/venv/bin/python -m pytest tests -q` |
| G2 differential ≥1000, byte-identical | 1229/1229, 0 diffs | `PYTHONPATH=/tmp/jm python3 tests/test_diff.py` |
| G3 median speedup ≥1.15x | 50.36x | `PYTHONPATH=/tmp/jm-base python3 benchmark/bench.py --impl baseline` then `PYTHONPATH=/tmp/jm python3 benchmark/bench.py --impl optimized` |
| G4 large scale ≥0.95x | 61.43x | same two commands, `large` row |
| G5 peak RSS ≤1.10x baseline | 20,916 KB vs 20,924 KB = 1.00x | `/usr/bin/time -v env PYTHONPATH=/tmp/jm python3 benchmark/bench.py --impl optimized` |

`/usr/bin/time -v` reported `Maximum resident set size (kbytes): 20924` for the baseline and `20916` for the optimized build. Upstream test RSS was 39,936 KB before and 40,448 KB after (also inside 1.10x). `git diff --stat` is 42 changed lines, under the 80-line limit. The benchmark clears `Parser._CACHE` before every timed parse so the parser's expression cache cannot mask the lexer cost.

## Reproduce

Three commands from a fresh clone of this repo (the first is also the smoke test; it needs the SSH remote `github-linluozi`):

```bash
git clone --depth=1 git@github-linluozi:jmespath/jmespath.py.git /tmp/jm && git -C /tmp/jm apply "$PWD/patch.diff" && PYTHONPATH=/tmp/jm python3 tests/test_diff.py
git clone --depth=1 git@github-linluozi:jmespath/jmespath.py.git /tmp/jm-base && PYTHONPATH=/tmp/jm-base python3 benchmark/bench.py --impl baseline
PYTHONPATH=/tmp/jm python3 benchmark/bench.py --impl optimized
```

For G1, install pytest and run the upstream suite against the patched checkout:

```bash
python3 -m venv /tmp/venv && /tmp/venv/bin/pip install pytest && cd /tmp/jm && /tmp/venv/bin/python -m pytest tests -q
```

## Environment

- CPU: `AMD EPYC 7K62 48-Core Processor` (4 vCPU)
- Memory: 3,812,564 kB total (3.6 GiB)
- Python: 3.12.3 (`/usr/bin/python3`), pytest 9.2.0 for upstream tests
- Seed: `20261031`; warmup 3; timed reps 5; clock `time.perf_counter()`
- Upstream commit: `2812594e69d43098ef60f81f4efc404c071b0418` (2026-01-22, `release-1.1.0` merge)
- Artifact layout: `benchmark/bench.py`, `benchmark/baseline.json`, `benchmark/optimized.json`, `benchmark/raw/*.json` (30 raw samples), `tests/test_diff.py`, `patch.diff`, `LICENSE`
