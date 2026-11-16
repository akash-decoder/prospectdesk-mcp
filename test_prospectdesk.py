import asyncio
import csv
import io
import os
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from starlette.testclient import TestClient

import prospectdb as db
from prospectweb import app


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / "leads.sqlite")
        env = patch.dict(os.environ, PROSPECTDESK_DB=self.path)
        env.start()
        self.addCleanup(env.stop)
        db.initialize()

    def test_retry_and_atomic_import(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            counts = list(pool.map(db.import_csv, [db.DEMO]*3))
        self.assertEqual(sum(x["added"] for x in counts),3)
        with self.assertRaises(ValueError):
            db.import_csv("company,website\nTemporary,\nRejected,invalid")
        self.assertEqual(db.search(db.Filters())["total"],3)

    def test_pipeline_and_shortlist(self):
        db.import_csv(db.DEMO)
        lead = db.search(db.Filters(website="unlisted",location="Hull",title="Owner",contact="email"))["leads"][0]
        db.update(lead["id"],stage="Qualified",note="Requested a preview",follow_up="2027-01-15")
        db.shortlist("Design", [lead["id"],lead["id"]])
        with self.assertRaises(ValueError):
            db.shortlist("Broken",[lead["id"],9999])
        db.import_csv(db.DEMO)
        self.assertEqual(db.list_names(),[{"list_name":"Design","count":1}])
        row = db.search(db.Filters(list_name="design",stage="Qualified"))["leads"][0]
        self.assertEqual(row["follow_up"],"2027-01-15")
        self.assertIn("Requested a preview",db.export_csv(db.Filters(list_name="Design")))

    def test_discovery(self):
        req = httpx.Request("POST","https://example.org")
        area = db.Area(latitude=53.75,longitude=-0.33,category="Photography")
        fixture = {"elements":[{"type":"node","id":1,"tags":{"name":"Example Studio","contact:website":"example.org"}}]}
        with patch("prospectdb.httpx.post",return_value=httpx.Response(200,json=fixture,request=req)) as provider:
            self.assertEqual(db.discover(area)["added"],1)
            self.assertEqual(db.discover(area)["matched"],1)
            self.assertIn('["craft"="photographer"]',provider.call_args.kwargs["data"]["data"])
        self.assertEqual(db.search(db.Filters(website="unlisted"))["total"],0)
        exported = next(csv.DictReader(io.StringIO(db.export_csv(db.Filters()))))
        self.assertEqual(exported["website"],"https://example.org")
        self.assertIn("OpenStreetMap",exported["attribution"])
        with patch("prospectdb.httpx.post",return_value=httpx.Response(429,request=req)), self.assertRaises(ValueError):
            db.discover(area)

    def test_web_entry_points(self):
        origin="http://127.0.0.1"
        with TestClient(app,base_url=origin) as client:
            self.assertIn("Discover businesses",client.get("/").text)
            self.assertEqual(client.post("/demo",headers={"Origin":"https://outside.example"}).status_code,403)
            self.assertIn("3 added",client.post("/demo",headers={"Origin":origin}).text)
            result=client.get("/?website=unlisted&title=Owner")
            self.assertIn("1 matching prospects",result.text)
            detail=client.get("/lead/1")
            self.assertIn("Alex Example",detail.text)
            file=client.post("/import",headers={"Origin":origin},files={"file":("example.csv",b"company,location\nSample,Hull","text/csv")})
            self.assertIn("1 added",file.text)
            self.assertIn("Sample",client.get("/export?location=Hull").text)
            self.assertEqual(client.get("/?stage=typo").status_code,400)

    def test_mcp_stdio_session(self):
        async def run():
            params=StdioServerParameters(command=sys.executable,args=["-m","prospectdesk","mcp"],env={"PROSPECTDESK_DB":self.path})
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as client:
                    await client.initialize()
                    self.assertEqual(len((await client.list_tools()).tools),10)
                    for name,args in [
                        ("import_leads",{"csv_text":db.DEMO}),
                        ("search_leads",{"filters":{"location":"Hull","contact":"email"}}),
                        ("draft_outreach",{"lead_id":1,"offer":"I design portfolio sites.","sender":"Alex"}),
                        ("export_leads",{"filters":{"location":"Hull"},"limit":1})]:
                        result=await client.call_tool(name,args)
                        self.assertFalse(result.isError, result.content)
        asyncio.run(run())
        self.assertEqual(db.search(db.Filters())["total"],3)
