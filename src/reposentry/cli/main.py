"""RepoSentry CLI — single entry point with subcommands and safe path handling."""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from reposentry import __version__
from reposentry.contracts.models import WINDOWS_RESERVED_DEVICE_NAMES

ANSI_ESCAPE_PATTERN = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def sanitize_cli_output(text: str) -> str:
    """Strip ANSI escape sequences from user-facing text to prevent terminal injection."""
    return ANSI_ESCAPE_PATTERN.sub("", text)


def validate_cli_target_path(path_str: str) -> Path:
    """Validate that target path is well-formed, exists, and is not a reserved system device."""
    raw = path_str.strip()
    if not raw:
        raise click.BadParameter("Target path cannot be empty.")

    p = Path(raw)
    base_name = p.stem.upper()
    if base_name in WINDOWS_RESERVED_DEVICE_NAMES:
        raise click.BadParameter(f"Reserved Windows device name is not allowed as a target: '{path_str}'")

    if not p.exists():
        raise click.BadParameter(f"Target path does not exist: '{path_str}'")

    return p.resolve()


@click.group()
@click.version_option(version=__version__, prog_name="reposentry")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output with full stack traces.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """RepoSentry: Evidence-backed architectural security-debt analyzer.

    Analyzes Python Flask/FastAPI repositories for architectural security
    patterns and produces evidence-backed findings with decomposed scores.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.argument("target", type=str)
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path.")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="json",
              help="Output format.")
@click.pass_context
def scan(ctx: click.Context, target: str, output: str | None, fmt: str) -> None:
    """Scan a repository for architectural security debt.

    TARGET is the path to the repository directory or archive to analyze.
    """
    try:
        resolved_path = validate_cli_target_path(target)
        click.echo(sanitize_cli_output(f"Scanning: {resolved_path} (format={fmt}, output={output})"))
        click.echo("Not yet implemented — skeleton only.")
    except Exception as exc:
        if ctx.obj.get("verbose"):
            raise
        click.echo(sanitize_cli_output(f"Error: {exc}"), err=True)
        sys.exit(1)


@cli.command()
def version() -> None:
    """Show version information."""
    click.echo(f"reposentry {__version__}")


@cli.command()
@click.argument("target", type=str)
@click.option("--output", "-o", type=click.Path(), default=None, help="Output workspace directory.")
@click.pass_context
def ingest(ctx: click.Context, target: str, output: str | None) -> None:
    """Ingest a repository into a read-only workspace.

    TARGET is the path to the directory or archive to ingest.
    """
    try:
        resolved_path = validate_cli_target_path(target)
        from reposentry.ingest.sandbox import WorkspaceSandbox

        sandbox = WorkspaceSandbox()
        if resolved_path.is_file() and resolved_path.suffix.lower() == ".zip":
            result = sandbox.ingest_archive(resolved_path, target_workspace=output)
        else:
            result = sandbox.ingest_directory(resolved_path, target_workspace=output)

        click.echo(
            sanitize_cli_output(
                f"Ingested {result.manifest.total_files} files into {result.workspace_dir} "
                f"(manifest_hash={result.manifest.manifest_hash[:12]})"
            )
        )
    except Exception as exc:
        if ctx.obj.get("verbose"):
            raise
        click.echo(sanitize_cli_output(f"Error: {exc}"), err=True)
        sys.exit(1)



@cli.command()
@click.argument("workspace", type=str)
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path.")
@click.pass_context
def parse(ctx: click.Context, workspace: str, output: str | None) -> None:
    """Parse an ingested workspace to extract route tables and symbols.

    WORKSPACE is the path to an ingested workspace directory.
    """
    try:
        resolved_path = validate_cli_target_path(workspace)
        click.echo(sanitize_cli_output(f"Parsing: {resolved_path} (output={output})"))
        click.echo("Not yet implemented — skeleton only.")
    except Exception as exc:
        if ctx.obj.get("verbose"):
            raise
        click.echo(sanitize_cli_output(f"Error: {exc}"), err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
