#!/usr/bin/env python3

import asyncio
import click

import main


@click.group()
def cli():
    pass


@click.command()
@click.option(
    "--port", default=8080, help="Web dashboard port", type=int
)
def serve(port: int):
    "Start the HideMyEmail web dashboard"
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main.serve(port))
    except KeyboardInterrupt:
        pass


@click.command()
@click.option(
    "--active/--inactive", default=True, help="Filter Active / Inactive emails"
)
@click.option("--search", default=None, help="Search by label")
def listcommand(active, search):
    "List emails (uses first account found)"
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(main.list_emails(active, search))
    except KeyboardInterrupt:
        pass


cli.add_command(serve, name="serve")
cli.add_command(listcommand, name="list")

if __name__ == "__main__":
    cli()
