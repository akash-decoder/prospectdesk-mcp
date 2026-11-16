"""Command line and MCP tools for ProspectDesk."""
import argparse
import csv

from mcp.server.fastmcp import FastMCP
from pydantic import Field
from typing import Annotated

import prospectdb as store

mcp = FastMCP("ProspectDesk")


@mcp.tool()
def search_leads(filters: store.Filters, limit: int = 50, offset: int = 0) -> dict:
    """Search stored prospects by company, title, area, industry, contact fields, list and stage."""
    return store.search(filters, limit, offset)


@mcp.tool()
def get_lead(lead_id: int) -> dict:
    """Read one prospect, its data source, pipeline stage, note and next follow-up date."""
    return store.get_lead(lead_id)


@mcp.tool()
def discovery_categories() -> list[str]:
    """List supported categories for public business discovery."""
    return list(store.CATEGORIES)


@mcp.tool()
def discover_businesses(area: store.Area) -> dict:
    """Search an area on OpenStreetMap and save matching business listings. Contact coverage varies."""
    return store.discover(area)


@mcp.tool()
def import_leads(csv_text: str) -> dict:
    """Import CSV text with a company header and optional person, title, industry, location, email, phone, website, source_url."""
    try:
        return store.import_csv(csv_text)
    except csv.Error as exc:
        raise ValueError(f"Malformed CSV: {exc}") from exc


@mcp.tool()
def add_to_list(list_name: str, lead_ids: list[int]) -> dict:
    """Add existing leads to a named shortlist; repeated membership is ignored."""
    return store.shortlist(list_name, lead_ids)


@mcp.tool()
def list_shortlists() -> list[dict]:
    """List saved shortlist names and their membership counts."""
    return store.list_names()


@mcp.tool()
def update_lead(lead_id: int, stage: store.Stage | None = None, note: str | None = None,
                follow_up: str | None = None) -> dict:
    """Update selected fields. Use YYYY-MM-DD for a follow-up date or an empty string to clear it."""
    return store.update(lead_id, stage, note, follow_up)


@mcp.tool()
def draft_outreach(lead_id: int, offer: Annotated[str, Field(min_length=1, max_length=800)],
                   sender: Annotated[str, Field(min_length=1, max_length=100)]) -> dict:
    """Prepare an editable plain-text first-contact draft from a saved prospect and your offer."""
    lead = store.get_lead(lead_id)
    greeting = lead["person"] or (lead["company"] + " team")
    body = f"Hi {greeting},\n\n{offer.strip()}\n\nWould this be useful for {lead['company']}?\n\n{sender.strip()}"
    return {"lead_id":lead_id, "to":lead["email"], "subject":f"A question for {lead['company']}", "body":body}


@mcp.tool()
def export_leads(filters: store.Filters, limit: Annotated[int, Field(ge=1, le=200)] = 100,
                 offset: Annotated[int, Field(ge=0)] = 0) -> dict:
    """Export a page of matching leads as CSV text. The web workspace also offers a full CSV download."""
    page = store.search(filters, limit, offset)
    return {"csv":store.to_csv(page["leads"]), "total":page["total"], "offset":offset}


def main():
    parser = argparse.ArgumentParser(description="ProspectDesk")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("mcp", help="Start the stdio MCP server")
    web = commands.add_parser("web", help="Start the private local browser workspace")
    web.add_argument("--port", default=8840, type=int)
    commands.add_parser("demo", help="Load three fictional sample leads")
    args = parser.parse_args()
    store.initialize()
    if args.command == "mcp":
        mcp.run(transport="stdio")
    elif args.command == "demo":
        print(store.import_csv(store.DEMO))
    else:
        import uvicorn
        uvicorn.run("prospectweb:app", host="127.0.0.1", port=args.port, proxy_headers=False)


if __name__ == "__main__":
    main()
