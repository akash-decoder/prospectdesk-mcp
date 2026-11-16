"""Persistent prospect records, public business discovery and follow-up lists."""
import csv
import hashlib
import io
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field

COLS = ("company", "person", "title", "industry", "location", "email", "phone", "website", "source_url")
STAGES = ("New", "Qualified", "Contacted", "Won", "Closed")
Stage = Literal["New", "Qualified", "Contacted", "Won", "Closed"]
CATEGORIES = {
    "Cleaning": ("craft", "cleaning"), "Plumbers": ("craft", "plumber"),
    "Electricians": ("craft", "electrician"), "Real estate": ("office", "estate_agent"),
    "Photography": ("craft", "photographer"), "Hair salons": ("shop", "hairdresser"),
    "Cafés": ("amenity", "cafe"), "Restaurants": ("amenity", "restaurant"),
    "Car repair": ("shop", "car_repair"), "Florists": ("shop", "florist")
}
OSM_CREDIT = "© OpenStreetMap contributors · https://www.openstreetmap.org/copyright"


class Filters(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    query: str = Field(default="", max_length=240)
    industry: str = Field(default="", max_length=120)
    location: str = Field(default="", max_length=160)
    title: str = Field(default="", max_length=120)
    stage: Stage | None = None
    list_name: str = Field(default="", max_length=100)
    website: Literal["any", "listed", "unlisted"] = "any"
    contact: Literal["any", "email", "phone"] = "any"


class Area(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=1500, ge=100, le=5000)
    category: str
    limit: int = Field(default=30, ge=1, le=100)


@contextmanager
def db():
    path = Path(os.environ.get("PROSPECTDESK_DB", "~/.prospectdesk/leads.sqlite3")).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize():
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS leads(
            id INTEGER PRIMARY KEY, identity TEXT UNIQUE NOT NULL,
            company TEXT NOT NULL, person TEXT, title TEXT, industry TEXT, location TEXT,
            email TEXT, phone TEXT, website TEXT, source_url TEXT, origin TEXT, observed TEXT,
            stage TEXT NOT NULL DEFAULT 'New', note TEXT NOT NULL DEFAULT '',
            follow_up TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS members(
            list_name TEXT COLLATE NOCASE NOT NULL, lead_id INTEGER REFERENCES leads(id),
            PRIMARY KEY(list_name,lead_id));
        """)


def is_web_url(value):
    try:
        url = urlsplit(value)
        return url.scheme in ("https","http") and bool(url.hostname) and url.username is None
    except ValueError:
        return False


def normalize(row):
    result = {key: (row.get(key) or "").strip() for key in COLS}
    if not result["company"]:
        raise ValueError("A company name is required")
    if any(len(v) > 2048 for v in result.values()):
        raise ValueError("A field exceeds 2,048 characters")
    for key in ("website", "source_url"):
        if result[key] and not is_web_url(result[key]):
            raise ValueError(f"{key} must be a complete http(s) URL")
    return result


def save_rows(rows, origin):
    added = updated = 0
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    # Preserve pipeline fields and list memberships across reimports.
    update_cols = ", ".join(f"{c}=CASE WHEN excluded.{c}<>'' THEN excluded.{c} ELSE leads.{c} END" for c in COLS)
    sql = f"""INSERT INTO leads(identity,{','.join(COLS)},origin,observed)
        VALUES({','.join('?' for _ in range(len(COLS)+3))})
        ON CONFLICT(identity) DO UPDATE SET {update_cols},observed=excluded.observed"""
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for identity, row in rows:
            exists = conn.execute("SELECT 1 FROM leads WHERE identity=?", (identity,)).fetchone()
            conn.execute(sql, (identity, *(row[c] for c in COLS), origin, stamp))
            if exists:
                updated += 1
            else:
                added += 1
    return {"added": added, "matched": updated}


def import_csv(csv_text):
    if len(csv_text.encode()) > 2_000_000:
        raise ValueError("Import up to 2 MB per batch")
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("\ufeff"), newline=""), strict=True)
    if not reader.fieldnames:
        raise ValueError("Missing CSV header")
    names = [c.strip().lower() for c in reader.fieldnames]
    if "company" not in names or len(set(names)) != len(names):
        raise ValueError("Use unique headers including company")
    reader.fieldnames = names
    rows = []
    for raw in reader:
        if len(rows) >= 5000 or None in raw:
            raise ValueError(f"Too many rows or extra columns at line {reader.line_num}")
        try:
            row = normalize(raw)
        except ValueError as exc:
            raise ValueError(f"Line {reader.line_num}: {exc}") from exc
        # Keep people/branches distinct, including when they share a company inbox.
        keys = [row[c].casefold() for c in ("company", "person", "location", "email")]
        identity = "csv:" + hashlib.sha256(json.dumps(keys).encode()).hexdigest()
        rows.append((identity, row))
    return save_rows(rows, "CSV")


def discover(area: Area):
    if area.category not in CATEGORIES:
        raise ValueError(f"Choose a category from {', '.join(CATEGORIES)}")
    key, value = CATEGORIES[area.category]
    query = (f'[out:json][timeout:20];nwr["{key}"="{value}"]["name"]'
             f'(around:{area.radius_m},{area.latitude},{area.longitude});out tags {area.limit};')
    try:
        response = httpx.post("https://overpass-api.de/api/interpreter", data={"data":query},
                              headers={"User-Agent":"ProspectDesk/0.1 (github.com/akash-decoder/prospectdesk-mcp)"},
                              timeout=30)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ValueError("OpenStreetMap discovery is unavailable. Retry later or import a CSV.") from exc
    if not isinstance(data, dict) or data.get("remark") or not isinstance(data.get("elements"), list):
        raise ValueError("The provider returned incomplete results. Try a smaller area.")
    rows = []
    for obj in data["elements"][:area.limit]:
        tags = obj.get("tags", {})
        if obj.get("type") not in ("node","way","relation") or not isinstance(obj.get("id"), int) or not tags.get("name"):
            continue
        source = f"https://www.openstreetmap.org/{obj['type']}/{obj['id']}"
        site = tags.get("contact:website") or tags.get("website","")
        if site and "://" not in site:
            site = "https://" + site
        if site and not is_web_url(site):
            continue
        row = normalize(dict(company=tags["name"], industry=area.category, source_url=source,
                             location=tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:suburb",""),
                             email=tags.get("contact:email") or tags.get("email",""),
                             phone=tags.get("contact:phone") or tags.get("phone",""),
                             website=site))
        rows.append((source,row))
    return dict(**save_rows(rows,"OpenStreetMap"), attribution=OSM_CREDIT)


def selection(filters):
    clauses, values = [], []
    if filters.query:
        clauses.append("(" + " OR ".join(f"instr(lower({c}),lower(?))>0" for c in COLS[:7]) + ")")
        values.extend([filters.query]*7)
    for col in ("industry","location","title"):
        term = getattr(filters,col)
        if term:
            clauses.append(f"instr(lower({col}),lower(?))>0")
            values.append(term)
    if filters.stage:
        clauses.append("stage=?")
        values.append(filters.stage)
    if filters.website != "any":
        clauses.append("website=''" if filters.website=="unlisted" else "website<>''")
    if filters.contact != "any":
        clauses.append(f"{filters.contact}<>''")
    if filters.list_name:
        clauses.append("id IN (SELECT lead_id FROM members WHERE list_name=?)")
        values.append(filters.list_name)
    return " FROM leads" + (" WHERE "+" AND ".join(clauses) if clauses else ""), values


PUBLIC = "id," + ",".join(COLS) + ",origin,observed,stage,note,follow_up"


def search(filters, limit=50, offset=0):
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError("Page size must be 1–200 and offset must be nonnegative")
    sql, params = selection(filters)
    with db() as conn:
        conn.execute("BEGIN")
        total = conn.execute("SELECT count(*)"+sql, params).fetchone()[0]
        rows = conn.execute("SELECT "+PUBLIC+sql+" ORDER BY company COLLATE NOCASE,id LIMIT ? OFFSET ?",
                            [*params,limit,offset])
        return {"total":total,"offset":offset,"leads":[dict(r) for r in rows]}


def get_lead(lead_id):
    with db() as conn:
        row = conn.execute("SELECT "+PUBLIC+" FROM leads WHERE id=?", (lead_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown lead ID")
        return dict(row)


def list_names():
    with db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT list_name,count(*) AS count FROM members GROUP BY list_name ORDER BY list_name")]


def shortlist(name, ids):
    name = name.strip()
    if not 1 <= len(name) <= 100 or not 1 <= len(ids) <= 200:
        raise ValueError("Supply a list name (1–100 characters) and 1–200 lead IDs")
    with db() as conn:
        try:
            conn.executemany("INSERT INTO members VALUES(?,?) ON CONFLICT DO NOTHING", ((name,i) for i in ids))
        except sqlite3.IntegrityError as exc:
            raise ValueError("One or more lead IDs do not exist") from exc
        return {"list_name":name,"count":conn.execute("SELECT count(*) FROM members WHERE list_name=?", (name,)).fetchone()[0]}


def update(lead_id, stage=None, note=None, follow_up=None):
    if stage is not None and stage not in STAGES:
        raise ValueError("Unknown stage")
    if follow_up:
        follow_up = date.fromisoformat(follow_up).isoformat()
    if note is not None and len(note) > 4000:
        raise ValueError("Notes support up to 4,000 characters")
    with db() as conn:
        result = conn.execute("""UPDATE leads SET stage=coalesce(?,stage),note=coalesce(?,note),
                              follow_up=coalesce(?,follow_up) WHERE id=?""", (stage,note,follow_up,lead_id))
        if not result.rowcount:
            raise ValueError("Unknown lead ID")
        return dict(conn.execute("SELECT "+PUBLIC+" FROM leads WHERE id=?", (lead_id,)).fetchone())


def to_csv(rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    fields = [*COLS,"origin","observed","stage","note","follow_up","attribution"]
    writer.writerow(fields)
    for row in rows:
        values = [row[c] for c in fields[:-1]] + [OSM_CREDIT if row["origin"]=="OpenStreetMap" else ""]
        writer.writerow(["'"+v if v.lstrip().startswith(("=","+","-","@")) or v.startswith(("\t","\r","\n")) else v for v in values])
    return stream.getvalue()


def export_csv(filters):
    sql, params = selection(filters)
    with db() as conn:
        return to_csv(conn.execute("SELECT "+PUBLIC+sql+" ORDER BY company,id", params))


DEMO = """company,person,title,industry,location,email,phone,website
Example Fern Studio,Alex Example,Owner,Photography,Hull,studio@example.com,,
Example Copper Works,, ,Plumbers,Leeds,,,https://example.org
Example Olive Care,Sam Example,Manager,Cleaning,Hull,care@example.net,,
"""
