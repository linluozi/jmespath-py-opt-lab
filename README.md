# jmespath-py-opt-lab

`jmespath.py` is the reference Python implementation of the JMESPath query language; this lab replaces the character-by-character loop in `Lexer._consume_until` with `str.find` + slice chunking, making uncached parsing of long string literals **49.1x** faster at the median scale on an independent fresh-clone re-run (44.8-56.9x across the three scales) with byte-identical output.

Upstream: https://github.com/jmespath/jmespath.py

## Result

Uncached parse of a single raw-string literal (`'<payload>'`), median of 5 timed runs after 3 warmups, `time.perf_counter()`, seed `20261031`. Two runs are reported: the committed run stored in `benchmark/*.json`, and an independent fresh-clone re-run.

Committed run (`benchmark/baseline.json`, `benchmark/optimized.json`):

| Scale | Payload | Baseline median | Optimized median | Speedup |
| --- | ---: | ---: | ---: | ---: |
| small | 8,192 B | 1.942 ms | 0.041 ms | 47.04x |
| medium | 32,768 B | 7.742 ms | 0.154 ms | 50.36x |
| large | 131,072 B | 30.878 ms | 0.503 ms | 61.43x |

Independent re-run from a fresh clone (verifier, same commands, separate machine session):

| Scale | Payload | Baseline median | Optimized median | Speedup |
| --- | ---: | ---: | ---: | ---: |
| small | 8,192 B | 1.943 ms | 0.043 ms | 44.83x |
| medium | 32,768 B | 7.588 ms | 0.133 ms | 56.87x |
| large | 131,072 B | 31.143 ms | 0.635 ms | 49.06x |

Median speedup across the three scales: **49.06x** on the independent re-run (50.36x on the committed run). The 128 KB optimized timing is bimodal across four independent runs (0.50 ms and 0.65 ms clusters), so its speedup ranges 46.3-61.9x; the baseline is stable at 30.3-31.2 ms (rel_stdev 0.5-1.9%). The headline uses the conservative 49.06x; the committed run is one draw from that distribution and its raw samples are kept in `benchmark/raw/`.

The gain comes from one function, `jmespath/lexer.py::Lexer._consume_until` (32 insertions, 10 deletions): the old code called `self._next()` and appended one character at a time; the new code locates the next delimiter/backslash with `str.find`, copies the whole run as one slice, and joins the chunks. For a 128 KB literal that removes ~131k Python-level loop iterations. The change only touches quoted identifiers, raw strings and backtick literals; no other token type or public API is modified.

Relative standard deviation was 1.1% / 0.3% / 0.4% for the baseline and 9.2% / 13.5% / 8.0% for the optimized build in the committed run. The optimized medium scale (13.5%) exceeds 10% because each sample is only ~0.15 ms, close to timer and scheduler granularity, with 5 samples per scale; the independent re-run shows the same effect (10-34% at sub-0.2 ms scales). Raw samples are kept in `benchmark/raw/`.

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
| G3 median speedup ≥1.15x | 49.06x (independent re-run; 50.36x committed) | `PYTHONPATH=/tmp/jm-base python3 benchmark/bench.py --impl baseline` then `PYTHONPATH=/tmp/jm python3 benchmark/bench.py --impl optimized` |
| G4 large scale ≥0.95x | 49.06x (independent re-run; 61.43x committed) | same two commands, `large` row |
| G5 peak RSS ≤1.10x baseline | 20,828 KB vs 21,784 KB = 0.96x (independent); 20,916 vs 20,924 = 1.00x (committed) | `/usr/bin/time -v env PYTHONPATH=/tmp/jm python3 benchmark/bench.py --impl optimized` |

`/usr/bin/time -v` reported `Maximum resident set size (kbytes): 20924` for the baseline and `20916` for the optimized build in the committed run, and 21,784 vs 20,828 KB in the independent re-run. Upstream test RSS was 39,936 KB before and 40,448 KB after (also inside 1.10x). `git diff --stat` is 42 changed lines, under the 80-line limit. The benchmark clears `Parser._CACHE` before every timed parse so the parser's expression cache cannot mask the lexer cost.

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
