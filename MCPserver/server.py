"""MCP server that fetches tech conference data from dev.events."""

import json
import os
from datetime import date
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("dev-events", host="0.0.0.0", port=8000)

BASE_URL = "https://dev.events"


def _parse_events(html: str) -> list[dict]:
    """Extract events from JSON-LD blocks in the HTML."""
    soup = BeautifulSoup(html, "html.parser")
    events = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if data.get("@type") == "EducationEvent":
                event = {
                    "name": data.get("name", ""),
                    "url": data.get("url", ""),
                    "start_date": data.get("startDate", ""),
                    "end_date": data.get("endDate", ""),
                    "description": data.get("description", ""),
                    "mode": _attendance_mode(data.get("eventAttendanceMode", "")),
                    "status": data.get("eventStatus", "").rsplit("/", 1)[-1],
                }
                location = data.get("location", {})
                if isinstance(location, dict):
                    address = location.get("address", {})
                    if isinstance(address, dict):
                        event["city"] = address.get("addressLocality", "")
                        event["country"] = address.get("addressRegion", "")
                performer = data.get("performer", {})
                if isinstance(performer, dict):
                    event["organizer"] = performer.get("name", "")
                events.append(event)
        except (json.JSONDecodeError, AttributeError):
            continue
    return events


def _attendance_mode(mode_url: str) -> str:
    if "Online" in mode_url:
        return "online"
    if "Offline" in mode_url:
        return "in-person"
    if "Mixed" in mode_url:
        return "hybrid"
    return "unknown"


def _format_events(events: list[dict], limit: int) -> str:
    """Format events list as readable text."""
    if not events:
        return "No events found."
    lines = [f"Found {len(events)} events (showing {min(limit, len(events))}):\n"]
    for ev in events[:limit]:
        date_start = ev.get("start_date", "")[:10]
        date_end = ev.get("end_date", "")[:10]
        location_parts = []
        if ev.get("city"):
            location_parts.append(ev["city"])
        if ev.get("country"):
            location_parts.append(ev["country"])
        location = ", ".join(location_parts) if location_parts else ev.get("mode", "")
        lines.append(f"- **{ev['name']}**")
        lines.append(f"  Date: {date_start} to {date_end}")
        lines.append(f"  Location: {location}")
        lines.append(f"  URL: {ev.get('url', '')}")
        lines.append("")
    return "\n".join(lines)


COUNTRY_TO_REGION = {
    "AL": "EU", "AD": "EU", "AT": "EU", "BY": "EU", "BE": "EU", "BA": "EU",
    "BG": "EU", "HR": "EU", "CY": "EU", "CZ": "EU", "DK": "EU", "EE": "EU",
    "FI": "EU", "FR": "EU", "DE": "EU", "GR": "EU", "HU": "EU", "IS": "EU",
    "IE": "EU", "IT": "EU", "LV": "EU", "LT": "EU", "LU": "EU", "MT": "EU",
    "MD": "EU", "ME": "EU", "NL": "EU", "MK": "EU", "NO": "EU", "PL": "EU",
    "PT": "EU", "RO": "EU", "RS": "EU", "SK": "EU", "SI": "EU", "ES": "EU",
    "SE": "EU", "CH": "EU", "UA": "EU", "GB": "EU", "TR": "EU",
    "US": "NA", "CA": "NA", "MX": "NA", "CR": "NA", "PA": "NA",
    "BR": "SA", "AR": "SA", "CL": "SA", "CO": "SA", "PE": "SA", "UY": "SA",
    "JP": "AS", "CN": "AS", "IN": "AS", "KR": "AS", "SG": "AS", "TW": "AS",
    "TH": "AS", "VN": "AS", "MY": "AS", "ID": "AS", "PH": "AS", "IL": "AS",
    "AE": "AS", "HK": "AS", "LK": "AS", "BD": "AS",
    "AU": "OC", "NZ": "OC",
    "ZA": "AF", "KE": "AF", "NG": "AF", "EG": "AF", "MA": "AF", "GH": "AF",
}


def _build_url(
    topic: Optional[str] = None,
    region: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Build dev.events URL from filter parameters."""
    path_parts = []
    cc = country.upper().strip() if country else None
    if region:
        path_parts.append(region.upper().strip())
    elif cc and cc in COUNTRY_TO_REGION:
        path_parts.append(COUNTRY_TO_REGION[cc])
    if cc:
        path_parts.append(cc)
    if city:
        path_parts.append(city.strip().replace(" ", "_"))
    if topic:
        path_parts.append(topic.lower().strip())

    path = "/".join(path_parts)
    url = f"{BASE_URL}/{path}" if path else BASE_URL

    params = {}
    today = date.today().isoformat()
    effective_start = start_date.strip() if start_date else None
    if effective_start and effective_start < today:
        effective_start = today
    if effective_start:
        params["startDate"] = effective_start
    if end_date:
        params["endDate"] = end_date.strip()
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{url}?{qs}"
    return url


@mcp.tool()
async def get_events(
    topic: Optional[str] = None,
    region: Optional[str] = None,
    country: Optional[str] = None,
    city: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 20,
) -> str:
    """Fetch upcoming tech conferences from dev.events.

    Args:
        topic: Filter by topic (e.g. ai, devops, kubernetes, python, java, cloud, security).
        region: Continent code (EU, NA, AS, AF, SA, OC, ON for online).
        country: Two-letter country code (DE, US, GB, FR, etc.).
        city: City name (e.g. Berlin, San_Francisco).
        start_date: Start of date range (YYYY-MM-DD).
        end_date: End of date range (YYYY-MM-DD).
        limit: Max number of events to return (default 20).
    """
    url = _build_url(topic, region, country, city, start_date, end_date)

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": "dev-events-mcp/1.0"})
        if resp.status_code >= 400:
            return f"Error: dev.events returned HTTP {resp.status_code} for {url}. Check filters."

    events = _parse_events(resp.text)
    return _format_events(events, limit)


@mcp.tool()
async def get_event_details(event_slug: str) -> str:
    """Get details for a specific conference from dev.events.

    Args:
        event_slug: The event slug from the URL path (e.g. 'sql-konferenz-2026').
    """
    url = f"{BASE_URL}/conferences/{event_slug}"
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        resp = await client.get(url, headers={"User-Agent": "dev-events-mcp/1.0"})
        resp.raise_for_status()

    events = _parse_events(resp.text)
    if not events:
        return f"No event data found for slug: {event_slug}"

    ev = events[0]
    parts = [
        f"# {ev['name']}",
        f"**Date:** {ev.get('start_date', '')[:10]} to {ev.get('end_date', '')[:10]}",
        f"**Mode:** {ev.get('mode', '')}",
        f"**Status:** {ev.get('status', '')}",
    ]
    if ev.get("city") or ev.get("country"):
        parts.append(f"**Location:** {ev.get('city', '')}, {ev.get('country', '')}")
    if ev.get("organizer"):
        parts.append(f"**Organizer:** {ev['organizer']}")
    if ev.get("description"):
        parts.append(f"**Description:** {ev['description']}")
    parts.append(f"**URL:** {ev.get('url', '')}")
    return "\n".join(parts)


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    if transport == "sse":
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")
