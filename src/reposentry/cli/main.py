"""RepoSentry CLI — single entry point with subcommands."""

from __future__ import annotations

import click

from reposentry import __version__


@click.group()
@click.version_option(version=__version__, prog_name="reposentry")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """RepoSentry: Evidence-backed architectural security-debt analyzer.

    Analyzes Python Flask/FastAPI repositories for architectural security
    patterns and produces evidence-backed findings with decomposed scores.
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.argument("target", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path.")
@click.option("--format", "fmt", type=click.Choice(["json", "text"]), default="json",
               help="Output format.")
def scan(target: str, output: str | None, fmt: str) -> None:
    """Scan a repository for architectural security debt.

    TARGET is the path to the repository directory or archive to analyze.
    """
    click.echo(f"Scanning: {target} (format={fmt}, output={output})")
    click.echo("Not yet implemented — skeleton only.")


@cli.command()
def version() -> None:
    """Show version information."""
    click.echo(f"reposentry {__version__}")


@cli.command()
@click.argument("target", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path.")
def ingest(target: str, output: str | None) -> None:
    """Ingest a repository into a read-only workspace.

    TARGET is the path to the directory or archive to ingest.
    """
    click.echo(f"Ingesting: {target} (output={output})")
    click.echo("Not yet implemented — skeleton only.")


@cli.command()
@click.argument("workspace", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path.")
def parse(workspace: str, output: str | None) -> None:
    """Parse an ingested workspace to extract route tables and symbols.

    WORKSPACE is the path to an ingested workspace directory.
    """
    click.echo(f"Parsing: {workspace} (output={output})")
    click.echo("Not yet implemented — skeleton only.")


if __name__ == "__main__":
    cli()
