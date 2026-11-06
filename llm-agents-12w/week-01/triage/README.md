# triage

A small Python project for week 1 of the LLM-agents course. It wraps the Anthropic SDK in one logged,
failure-aware function (`call()`), then uses it to generate fake production incidents (logs, metrics,
ground truth) that later weeks will ask a model to diagnose.

This README explains each file from a Python developer's point of view, including the packaging
parts that tend to be confusing.

---

## 1. Layout

```text
triage/
  pyproject.toml              # packaging + dependencies (the "setup.py" of modern Python)
  .env                        # secrets, loaded at runtime (never commit)
  runs.jsonl                  # append-only log, one JSON line per model call
  src/
    triage/                   # the importable package: `import triage`
      __init__.py             # empty; marks the folder as a package
      llm.py                  # call() wrapper, cost calculation, logging
      schemas.py              # Pydantic models: IncidentSummary, Evidence
      summarize.py            # prompt text, prompt builder, citation checker
      cli.py                  # `triage summarize <folder>` command (Typer)
  scripts/
    gen_incidents.py          # builds data/ (uses the model + deterministic code)
    review_scenarios.py       # sanity-checks the generated scenarios
    review_scenarios_result.md  # saved output of the review script
  data/
    scenarios/INC-00N.json    # what the model produced (structured output)
    incidents/INC-00N/        # what code expanded it into: app.log, alert.txt, metrics.csv, truth.json
```

How the pieces fit: `cli.py` reads an incident folder, `summarize.py` builds the prompt, `llm.py` makes the
call, `schemas.py` defines the shape of the answer, and `summarize.py` then checks the model's citations
against the real log.

---

## 2. Setup and running

```bash
cd sputnik/llm-agents-12w/week-01/triage
python3 -m venv .venv                 # or use your existing venv
source .venv/bin/activate
pip install -e ".[dev]"               # editable install of this project + ipykernel
```

Put your key in `.env`:

```text
ANTHROPIC_API_KEY=sk-ant-...
```

Run everything **from the `triage/` folder** (see "Gotchas" for why):

```bash
python scripts/gen_incidents.py                 # calls the model, rewrites data/
python scripts/gen_incidents.py --expand-only   # no model calls, re-expands data/scenarios/*.json
python scripts/review_scenarios.py              # prints a review of each scenario + flags

triage summarize data/incidents/INC-001                    # the CLI (installed by pip install -e .)
triage summarize data/incidents/INC-001 --stream --effort medium
python -m triage.cli summarize data/incidents/INC-001      # same thing without the `triage` command
```

---

## 3. File by file

### `pyproject.toml`

The single config file for the project (PEP 621). Block by block:

- `[project]` holds the name, version and Python requirement (`>=3.11`).
- `dependencies` are what `pip` installs for you: `anthropic`, `pydantic`, `python-dotenv`, `typer`, `pandas`.
- `[project.optional-dependencies] dev = ["ipykernel"]` is an *extra*. It is only installed if you ask for it:
  `pip install -e ".[dev]"`. Here it lets Jupyter/VS Code use the venv as a notebook kernel.
- `[project.scripts] triage = "triage.cli:app"` creates a shell command `triage` that imports
  `triage/cli.py` and calls the object named `app` (a Typer app). Format is `command = "module:object"`.
- `[build-system]` says *how* to build the package. `hatchling` is just the build tool; you never call it directly.
- `[tool.hatch.build.targets.wheel] packages = ["src/triage"]` tells hatchling where the package lives.
  This is needed because of the `src/` layout (next section).

### The `src/` layout and `pip install -e .`

This is the part that most often confuses people.

- Code lives in `src/triage/`, not `triage/`. That prevents you from accidentally importing the folder next
  to you instead of the installed package, so tests and scripts behave like real users of the package.
- Python only imports what is on `sys.path`. `src/` is **not** on it by default. `pip install -e .`
  (an *editable* install) solves that: it installs a tiny pointer into your venv's `site-packages` that
  says "`triage` lives in `.../triage/src/triage`".
- After that, `from triage.llm import call` works from any folder, and edits to `llm.py` take effect
  immediately without reinstalling.
- It is **per venv**. If you switch venvs, you must run `pip install -e .` again. If you see
  `ModuleNotFoundError: No module named 'triage'`, this is almost always the cause.
- You only need to rerun it if `pyproject.toml` changes (new dependency, new script entry).

### `src/triage/__init__.py`

Empty on purpose. Its presence marks `triage/` as a regular package. (Python can import folders without it,
as "namespace packages", but a regular package behaves more predictably with tools and packaging.)
You could later re-export things here, e.g. `from .llm import call`, so users can write `from triage import call`.

### `src/triage/llm.py`

The core of the project. Top to bottom:

**Module-level code runs at import time.** Importing `triage.llm` immediately does three things:

1. `load_dotenv()` reads a `.env` file and puts its values into `os.environ`. It looks in the **current
   working directory** and walks up parent folders, so where you run Python matters.
2. `client = anthropic.Anthropic()` creates one shared client. It reads `ANTHROPIC_API_KEY` from the
   environment, and raises right at import if there is no key. It reuses connections and retries
   failed requests twice by default.
3. `RUNS = Path("runs.jsonl")` is a **relative** path, resolved against the current working directory
   each time it is used, not against this file's location.

**Pricing.** `PRICES` maps model to `(input, output)` dollars per million tokens. `LONG_TIER` overrides
those prices when the prompt is above a size threshold. `cost_usd()` turns the `usage` object from the API
into dollars (cache writes cost 1.25x input, cache reads 0.10x).

**`LLMError`.** A custom exception for "the API call succeeded, but the result is unusable" (cut off or refused).
It subclasses `RuntimeError`, so `except LLMError` catches only this case, not network errors.

**`_log(rec)`.** The leading underscore means "internal, not part of the public API". It opens `runs.jsonl`
in append mode (`"a"`) and writes one JSON object per line. That's the JSON Lines format: easy to append to,
easy to read with `pandas.read_json("runs.jsonl", lines=True)`.

**`text_of(r)`.** Joins only the `text` blocks of a response. A reply's `content` is a *list* of blocks
(text, thinking, tool use, ...), so `r.content[0].text` can break; this helper doesn't.

**`call(...)`.** The one function the rest of the project uses.

- `messages` may be a plain string (wrapped into one user message) or a full list of messages.
- The bare `*` in the signature makes everything after it **keyword-only**: `call("hi", tag="x")` works,
  `call("hi", "sys", "model")` does not.
- It builds `kw`, a dict of arguments, and passes it with `**kw`. That's how it switches between three SDK
  methods with the same arguments: `messages.stream(...)`, `messages.parse(...)` (structured output into a
  Pydantic class) and `messages.create(...)`.
- `rec |= {...}` merges a dict into `rec` in place (dict union, Python 3.9+).
- Failures (`anthropic.APIError`) are logged, then re-raised with a bare `raise`, so the traceback is kept.
- On success it logs **before** checking `stop_reason`, so truncated or refused calls still show up in
  `runs.jsonl`, then raises `LLMError` for `max_tokens` and `refusal`.
- `thinking_tokens`, `ttft_s` (time to first token) and `request_id` are recorded so you can compare
  models and effort levels from data later.

### `src/triage/schemas.py`

The shape of the answer you want from the model, written as Pydantic models.

- A `BaseModel` is a class whose attributes are typed fields. Pydantic validates and converts data on
  creation, and raises `ValidationError` if it doesn't fit.
- `Field(ge=1)` / `Field(ge=0, le=1)` are constraints (greater-or-equal, less-or-equal).
  `min_length=1, max_length=8` on a list limits how many items it may hold.
- `Literal["sev1", ...]` allows only those exact strings.
- `first_error_ts: datetime` makes Pydantic parse an ISO timestamp string into a real `datetime`.
- `Field(description=...)` is documentation *and* an instruction: the text goes into the JSON schema that is
  sent to the model.
- `call(..., schema=IncidentSummary)` in `llm.py` passes this class to the SDK, which turns it into a JSON
  schema for the API, then gives back a validated `IncidentSummary` object as `r.parsed_output`.
- `Evidence` is a nested model: one cited log line (`line` number plus verbatim `text`).

### `src/triage/summarize.py`

Three things, none of which call the API.

- `SYSTEM` is the system prompt. Note the instructions to treat anything inside `<alert>`, `<logs>`, `<metrics>`
  as data, not commands (basic prompt-injection defence), and to cite lines by number plus exact text.
- `build_prompt(folder)` reads `alert.txt`, `app.log` and `metrics.csv` from an incident folder and returns one
  string. `enumerate(log, start=1)` prefixes every log line with its 1-based number and a tab, so the model can
  cite line numbers instead of guessing. XML-style tags separate the sections.
- `check_citations(summary, folder)` is the safety net. For each piece of evidence it checks that the line number
  is in range and that the cited text equals the real line (`log[ev.line - 1]`, since Python lists are
  0-based). It returns a list of problem strings; an empty list means every citation is real.
- `from .schemas import IncidentSummary` is a **relative import**: the dot means "from this same package".
  It works when the file is imported as `triage.summarize` (installed package), not when run directly as a script.

### `src/triage/cli.py`

The command-line entry point, built with [Typer](https://typer.tiangolo.com/), which turns ordinary functions and
type hints into a CLI.

- `app = typer.Typer(no_args_is_help=True)` is the application object. This is the `app` that
  `pyproject.toml` refers to in `triage = "triage.cli:app"`; after `pip install -e .`, typing `triage` runs it.
- `@app.callback()` on `main()` exists so Typer keeps `summarize` as a named subcommand. With only one command,
  Typer would otherwise make it the default and you'd type `triage <folder>` with no `summarize`.
- `@app.command()` registers `summarize` as a subcommand. Typer builds the arguments from the signature:
  - `folder: Path` is a required positional argument, converted to a `Path`.
  - `stream: bool = typer.Option(False, "--stream")` is a flag: `--stream` turns it on.
  - `model: str = "claude-haiku-5-5"` and `effort: str = "low"` become `--model` and `--effort` options.
  - The docstring becomes the `--help` text.
- The flow: build the prompt, `call(...)` with `schema=IncidentSummary`, take `r.parsed_output`, run
  `check_citations`, print the JSON to **stdout**, and print status messages to **stderr** (`err=True`).
  Keeping JSON on stdout means you can pipe it (`triage summarize ... > out.json`) while messages stay on screen.
- If citations fail it exits with `raise typer.Exit(1)`: a non-zero exit code, so scripts and CI can detect it.
- `if __name__ == "__main__": app()` lets you also run it as `python -m triage.cli summarize ...`.
  Use `-m`, not `python src/triage/cli.py`, or the relative imports will fail.
- Because `llm.py` uses a relative `runs.jsonl`, run the command from `triage/`.

### `scripts/gen_incidents.py`

Builds the dataset. It splits the work in two on purpose:

- **Model part:** `Scenario` (a Pydantic `BaseModel`) describes the shape the model must return: service,
  alert text, root cause, log line *templates*, a metric. `Field(description=...)` text is sent to the model
  as part of the schema, so it acts as instructions. `generate()` calls `call(..., schema=Scenario)` and reads
  `r.parsed_output`, which is already a validated `Scenario` object.
- **Code part:** `expand()` turns a scenario into files. It's deterministic: `random.Random(seed)` makes
  its own random generator, so the same seed always gives identical files. It writes ~3000 log lines, a
  per-minute metrics CSV and `truth.json`. The ground truth (which line is the trigger, which is the first
  error) is **computed from what was written**, never taken from the model, so you can trust it when grading.
- `if __name__ == "__main__":` runs the generation only when you execute the file directly, not when it is
  imported. `--expand-only` re-runs `expand()` on `data/scenarios/*.json` (useful after hand-editing one)
  without any API calls.
- Paths like `data/scenarios` are relative to where you run it, so run from `triage/`.
- `from triage.llm import call` works because of the editable install, even though the script is in `scripts/`.

### `scripts/review_scenarios.py`

A plain linting script for the generated data. It prints each scenario and flags mechanical problems:
trigger isn't an INFO line, wrong number of templates, the error signature leaking into noise lines, or
the same signature used by two incidents. It's top-level code with no functions, which is fine for a
throwaway script.

### `scripts/review_scenarios_result.md`

Saved output of the script above. Worth reading: the first run flagged that INC-001 and INC-002 both use
`PoolTimeout` as their signature, which would make two incidents hard to tell apart, and several error
templates "MISSING-SIG". That is the kind of problem to fix by editing the scenario JSON and re-running
`--expand-only`.

### `data/`

Generated output; you can delete and regenerate it.

- `scenarios/INC-00N.json` is the model's structured answer (templates, not real logs).
- `incidents/INC-00N/` is the expanded data a diagnosing model would see (`app.log`, `alert.txt`,
  `metrics.csv`) plus `truth.json`, the answer key.

### `runs.jsonl`

One JSON line per API call (tag, model, tokens, cost, latency, ok/error). Appended to by `_log`. Handy for
checking costs, e.g. `pandas.read_json("runs.jsonl", lines=True).cost_usd.sum()`.

### `.env`

`KEY=value` lines read by `load_dotenv()`. Needs `ANTHROPIC_API_KEY`. It also contains an
`OPENAI_API_KEY`, which nothing in this project uses. Make sure `.env` is in a `.gitignore` so it is never committed.

### `__pycache__/`, `.venv/`, `*.egg-info`

Generated. `__pycache__` holds compiled bytecode Python caches automatically. `.venv` is your virtual
environment. None of these should be committed.

---

## 4. Gotchas

- **Relative imports need `-m` or the installed package.** `from .llm import call` fails with
  `ImportError: attempted relative import with no known parent package` if you run a file inside `src/triage/`
  directly. Use `triage ...` or `python -m triage.cli ...`.
- **Run from `triage/`.** `.env` discovery, `runs.jsonl` and `data/...` are all relative to the current
  working directory. Running from elsewhere silently writes `runs.jsonl` into the wrong folder, or fails to find the key.
  In a notebook, `os.chdir(...)` into `triage/` first (that is what `scratch-pad/01_poke.ipynb` does).
- **`ModuleNotFoundError: triage`** means the active interpreter/kernel isn't the venv where you ran
  `pip install -e .`. Check with `python -c "import sys; print(sys.executable)"`.
- **Importing has side effects.** `import triage.llm` loads `.env` and builds the client, so a missing key
  fails at import time rather than at the first call.
- **After editing `llm.py` in a notebook**, restart the kernel (or use `importlib.reload`); Python caches
  imported modules.
- **Model names and prices are hard-coded** in `PRICES`. Using a model that isn't in that dict raises a
  `KeyError` in `cost_usd()` *after* the API call was already made and paid for.
