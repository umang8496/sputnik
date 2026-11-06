# =============================================================================
# cli.py: how `triage` became a command you can type in the terminal
# =============================================================================
#
# THE SHORT VERSION
# -----------------
# Nothing in this file "makes" a command. Three separate things combine:
#
#   1. THIS FILE defines a Typer object called `app`. It is an ordinary Python
#      object that knows how to read command-line arguments and call functions.
#
#   2. pyproject.toml contains this line:
#
#          [project.scripts]
#          triage = "triage.cli:app"
#
#      Read it as:  command-name = "python.module.path:object-name"
#      i.e. "a command called `triage` should import the module `triage.cli`
#      and call the object named `app`".
#      On its own this is only a declaration; nothing happens yet.
#
#   3. `pip install -e .` reads that declaration and CREATES A SMALL EXECUTABLE
#      FILE in your venv's bin/ folder, named `triage`. That file is the actual
#      command. You can open it with `cat venv-3.14/bin/triage`; it is just:
#
#          #!/path/to/venv/bin/python3.14      <- run with the venv's Python
#          import sys
#          from triage.cli import app          <- import THIS file, get `app`
#          if __name__ == '__main__':
#              sys.exit(app())                 <- call it, exit with its result
#
#      pip also records the declaration in
#      site-packages/triage-0.1.0.dist-info/entry_points.txt under
#      [console_scripts]. ("console_scripts" is the standard Python name for
#      "turn this function into a terminal command".)
#
# So when you type:   triage summarize data/incidents/INC-001
#
#   shell  -> finds `triage` in the venv's bin/ folder (on PATH once the venv
#             is activated, or call it by full path)
#          -> that tiny script runs under the venv's Python
#          -> it imports this module (triage.cli) and calls app()
#          -> Typer reads sys.argv ("summarize", "data/incidents/INC-001")
#          -> Typer finds the function registered as `summarize` below and
#             calls it with folder=Path("data/incidents/INC-001")
#
# WHY IT DISAPPEARS WHEN YOU CHANGE VENVS
# ---------------------------------------
# The `triage` executable is created by `pip install -e .` and lives inside
# ONE venv. A different venv has no such file until you run the install there.
# Run `which triage` to see which one you are using; no output means this venv
# never installed the project.
#
# WHY RENAMING THINGS BREAKS IT
# -----------------------------
# "triage.cli:app" is just text that is turned into an import at run time.
# If you rename this file, or rename the variable `app`, the command fails with
# ImportError until you update pyproject.toml AND re-run `pip install -e .`
# (the generated script is a copy, so it does not notice pyproject changes).
#
# THE TWO OTHER WAYS TO RUN THE SAME CODE
# ---------------------------------------
#   python -m triage.cli summarize <folder>
#       -m means "run this module as a program". It goes through the
#       `if __name__ == "__main__": app()` block at the bottom of this file.
#       No generated command needed, but the package must still be importable.
#
#   python src/triage/cli.py ...      <- DON'T. Running the file directly means
#       it is not part of a package, so `from .llm import call` fails with
#       "attempted relative import with no known parent package".
# =============================================================================

import json  # currently unused; safe to delete
from pathlib import Path

import typer  # Typer: builds a CLI from ordinary functions and type hints

# The dots mean "relative import: from the same package as this file".
# `.llm` is triage/llm.py, `.schemas` is triage/schemas.py, and so on.
# These work only when this file is loaded as `triage.cli` (installed package,
# the `triage` command, or `python -m triage.cli`).
from .llm import call
from .schemas import IncidentSummary
from .summarize import SYSTEM, build_prompt, check_citations

# `app` is the object that pyproject.toml points at ("triage.cli:app").
# It is a registry: the decorators below add commands to it, and calling
# app() later parses the terminal arguments and runs the matching command.
#
# no_args_is_help=True: typing just `triage` (nothing after it) prints the
# help page instead of failing with an error.
app = typer.Typer(no_args_is_help=True)


# @app.callback() marks a function that belongs to the whole app rather than
# to one command. Its docstring becomes the top-level description shown in
# `triage --help` ("Incident triage tools.").
#
# The real reason it is here: Typer has a quirk. If an app has exactly ONE
# command, Typer makes it the default, so you would have to type
# `triage <folder>` and the word "summarize" would not exist. Declaring a
# callback tells Typer "this is a multi-command app", so `summarize` stays a
# named subcommand: `triage summarize <folder>`. It also leaves room to add
# more commands later (e.g. `triage score`) without changing how this one is called.
@app.callback()
def main():
    """Incident triage tools."""


# @app.command() registers this function as a subcommand named after the
# function: `summarize`. Typer inspects the signature and type hints and builds
# the command-line interface from them, so you never write argument parsing:
#
#   folder: Path
#       No default value -> REQUIRED positional argument.
#       The `Path` hint makes Typer convert the text you type into a Path
#       object before calling the function.
#           triage summarize data/incidents/INC-001
#
#   stream: bool = typer.Option(False, "--stream")
#       A bool with a default of False -> an on/off FLAG. Passing --stream
#       sets it to True. "--stream" is the flag name you type. (typer.Option
#       is only needed here to choose that exact name; a plain `stream: bool = False`
#       would give you --stream / --no-stream.)
#           triage summarize data/incidents/INC-001 --stream
#
#   model: str = "claude-haiku-5-5"
#   effort: str = "low"
#       Arguments WITH a default become optional --options; the name comes
#       from the parameter name (underscores become dashes).
#           triage summarize data/incidents/INC-001 --model claude-sonnet-5-5 --effort medium
#
# The docstring below is the text shown by `triage summarize --help`.
@app.command()
def summarize(folder: Path, stream: bool = typer.Option(False, "--stream"),
              model: str = "claude-haiku-5-5", effort: str = "low"):
    """Turn a raw incident folder into a validated IncidentSummary JSON."""

    # 1. build_prompt(folder) reads alert.txt, app.log and metrics.csv from the
    #    folder and returns one big prompt string (log lines are numbered).
    # 2. call(...) is the wrapper from llm.py. `schema=IncidentSummary` asks the
    #    API for JSON matching that Pydantic class. The call is also logged to
    #    runs.jsonl, with the folder name as the tag (e.g. "summarize:INC-001").
    r = call(build_prompt(folder), system=SYSTEM, model=model, effort=effort,
             schema=IncidentSummary, stream=stream, tag=f"summarize:{folder.name}")

    # r.parsed_output is already a validated IncidentSummary object: if the
    # model's JSON had broken the schema, Pydantic would have raised an error.
    summary: IncidentSummary = r.parsed_output

    # Pydantic can only check SHAPE (right types, ranges). It cannot know
    # whether the model invented a log line. check_citations compares each cited
    # line number and text against the real app.log and returns a list of
    # problems (empty list = every citation is genuine).
    problems = check_citations(summary, folder)

    # The result goes to STDOUT (plain print). That means you can redirect it:
    #     triage summarize data/incidents/INC-001 > summary.json
    # and the file will contain only the JSON.
    print(summary.model_dump_json(indent=2))

    # Status messages go to STDERR (err=True), so they appear on screen but are
    # NOT mixed into the JSON when you redirect or pipe stdout.
    if problems:
        typer.echo("CITATION CHECK FAILED:\n" + "\n".join(problems), err=True)
        # typer.Exit(1) ends the program with exit code 1. By Unix convention
        # 0 means success and anything else means failure, so shell scripts and
        # CI jobs can detect the failure: `triage summarize ... || echo failed`.
        raise typer.Exit(1)
    typer.echo(f"citations OK ({len(summary.evidence)})", err=True)


# Runs only when this file is executed as a program (`python -m triage.cli ...`),
# NOT when it is imported. When the generated `triage` script does
# `from triage.cli import app`, this block is skipped, because the module name is
# "triage.cli" rather than "__main__"; the script calls app() itself.
if __name__ == "__main__":
    app()
