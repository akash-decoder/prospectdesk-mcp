"""Single-user, server-rendered workspace. All writes use same-origin POST forms."""
import csv
from urllib.parse import urlencode

from jinja2 import Environment
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from starlette.routing import Route

import prospectdb as store

TEMPLATE = Environment(autoescape=True).from_string("""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{title}} · ProspectDesk</title>
<style>
:root { --ink:#162e2c; --green:#1c5446; --paper:#f5f5ec; --line:#cbd2c2; --lime:#dcf390;
font:16px/1.5 "DM Sans","Segoe UI",sans-serif; color:var(--ink); background:var(--paper) }
* {box-sizing:border-box} body {margin:0} header {background:var(--ink);color:white;padding:15px max(5vw,18px);
display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap} header a {color:white;text-decoration:none}
.brand {font-size:1.3rem;font-weight:750;letter-spacing:-.05em}.brand b {color:var(--lime)}
nav,.row {display:flex;gap:14px;align-items:center;flex-wrap:wrap} nav a {padding:6px 0}
main {max-width:1240px;margin:auto;padding:34px max(4vw,16px)} h1 {font:clamp(2.4rem,6vw,4.8rem)/1.04 Georgia,serif;
letter-spacing:-.055em;margin:12px 0 24px} h2 {margin:0 0 12px;font-size:1.2rem} a {color:var(--green)}
section,article {background:#fffef8;border:1px solid var(--line);padding:20px;border-radius:12px;margin:14px 0}
.grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr));gap:12px}
label {display:block;font-weight:600;font-size:.85rem} input,select,textarea {display:block;margin:4px 0 10px;
width:100%;padding:10px;background:white;color:var(--ink);border:1px solid #a5b2a4;border-radius:5px;font:inherit}
input[type=checkbox] {width:18px;height:18px} button,.button {background:var(--green);color:white;
border:0;border-radius:6px;padding:10px 16px;min-height:42px;cursor:pointer;font:600 .92rem/1.4 inherit;
font-family:inherit;text-decoration:none} .button.light {background:var(--lime);color:var(--ink)}
a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible,textarea:focus-visible {outline:3px solid #a76825;outline-offset:2px}
.tablewrap {overflow-x:auto}table {border-collapse:collapse;width:100%} th,td {text-align:left;padding:12px;border-bottom:1px solid var(--line)}
th {font-size:.77rem;text-transform:uppercase;letter-spacing:.05em} small,footer {color:#53675c}
footer {padding:20px 0;font-size:.83rem} .tag {background:#e3edda;padding:4px 9px;border-radius:12px;font-size:.8rem}
.notice {border-left:4px solid var(--green);padding:10px;background:#e5f1dc} dl {display:grid;grid-template-columns:minmax(90px,160px) 1fr;gap:8px}
dd {margin:0;overflow-wrap:anywhere} summary {cursor:pointer;padding:8px 0} .wide {max-width:810px}
</style></head><body><header><a class="brand" href="/"><b>◒</b> ProspectDesk</a>
<nav aria-label="Workspace"><a href="/">Prospects</a><a href="/discover">Discover</a><a href="/import">Import CSV</a></nav></header>
<main><h1>{{title}}</h1>{% if message %}<p class="notice" role="status">{{message}}</p>{% endif %}
{% if view=='home' %}
<section><form method="get"><label>Search prospects<input name="query" value="{{f.query}}" placeholder="Company, person, job title or contact detail"></label>
<div class="grid">{% for key in ['industry','location','title'] %}<label>{{key|capitalize}}<input name="{{key}}" value="{{f[key]}}"></label>{% endfor %}
<label>Website<select name="website">{% for v,n in [('any','Any'),('listed','Listed'),('unlisted','No website listed')] %}
<option value="{{v}}" {% if f.website==v %}selected{% endif %}>{{n}}</option>{% endfor %}</select></label>
<label>Contact<select name="contact">{% for v in ['any','email','phone'] %}<option value="{{v}}" {% if f.contact==v %}selected{% endif %}>{{v|capitalize}}</option>{% endfor %}</select></label>
<label>Stage<select name="stage"><option value="">Any</option>{% for v in stages %}<option {% if f.stage==v %}selected{% endif %}>{{v}}</option>{% endfor %}</select></label>
<label>Shortlist<select name="list_name"><option value="">All</option>{% for l in lists %}<option {% if f.list_name==l.list_name %}selected{% endif %}>{{l.list_name}}</option>{% endfor %}</select></label></div>
<div class="row"><button>Apply filters</button><a href="/">Reset</a></div></form></section>
<section><div class="row"><h2>{{results.total}} matching prospects</h2><a href="/export?{{qs}}">Export results</a></div>
{% if results.leads %}<form method="post" action="/shortlist"><div class="tablewrap"><table><thead><tr><th>Select</th><th>Company / contact</th><th>Industry</th><th>Location</th><th>Stage</th><th>Follow-up</th></tr></thead>
<tbody>{% for r in results.leads %}<tr><td><input type="checkbox" name="ids" value="{{r.id}}" aria-label="Select {{r.company}}"></td>
<td><a href="/lead/{{r.id}}"><b>{{r.company}}</b></a><br><small>{{r.person or r.email or r.phone}}</small></td><td>{{r.industry or '—'}}</td>
<td>{{r.location or '—'}}</td><td><span class="tag">{{r.stage}}</span></td><td>{{r.follow_up or '—'}}</td></tr>{% endfor %}</tbody></table></div>
<label>Shortlist name<input name="name" placeholder="Hull prospects" required maxlength="100"></label><button>Add selected to list</button></form>
<div class="row">{% if offset %}<a href="/?{{qs}}&offset={{[0,offset-50]|max}}">Previous page</a>{% endif %}
{% if offset+50 < results.total %}<a href="/?{{qs}}&offset={{offset+50}}">Next page</a>{% endif %}</div>
{% else %}<p>Discover businesses by area, import a contact list, or adjust your filters.</p>
<div class="row"><a class="button light" href="/discover">Discover businesses</a><a href="/import">Import CSV</a></div>{% endif %}</section>
{% elif view=='discover' %}<section class="wide"><h2>Search OpenStreetMap</h2><p>Enter a map centre and radius to add nearby businesses to your workspace. Contact details depend on what contributors have listed.</p>
<form method="post" action="/discover"><label>Business category<select name="category">{% for c in categories %}<option>{{c}}</option>{% endfor %}</select></label>
<div class="grid">{% for name,label,val,lo,hi,step in [('latitude','Latitude',53.7457,-90,90,'any'),('longitude','Longitude',-0.3367,-180,180,'any'),('radius_m','Radius (metres)',1500,100,5000,1),('limit','Max listings',30,1,100,1)] %}
<label>{{label}}<input type="number" name="{{name}}" step="{{step}}" value="{{val}}" min="{{lo}}" max="{{hi}}" required></label>{% endfor %}</div>
<small>Starting location: Hull, UK.</small><p><button>Find and save businesses</button></p></form></section>
{% elif view=='import' %}<section class="wide"><h2>Import a contact list</h2><p>Choose a UTF-8 CSV or paste its contents. Include a <code>company</code> column. Optional columns are <code>person, title, industry, location, email, phone, website, source_url</code>.</p>
<form action="/import" method="post" enctype="multipart/form-data"><label>CSV file<input name="file" type="file" accept=".csv,text/csv"></label>
<label>CSV text<textarea rows="5" name="text" placeholder="company,industry,location"></textarea></label><button>Import leads</button></form></section>
<section class="wide"><h2>Try the workspace</h2><form action="/demo" method="post"><button>Load 3 fictional examples</button></form></section>
{% elif view=='lead' %}<section class="wide"><h2>Prospect details</h2><dl>
{% for k in ['person','title','industry','location','email','phone','website','source_url','origin','observed'] %}
<dt>{{k.replace('_',' ')|capitalize}}</dt><dd>{% if k in ['website','source_url'] and lead[k] %}<a href="{{lead[k]}}" rel="noreferrer">{{lead[k]}}</a>{% else %}{{lead[k] or 'Not listed'}}{% endif %}</dd>{% endfor %}</dl></section>
<section class="wide"><h2>Pipeline</h2><form method="post"><div class="grid"><label>Stage<select name="stage">{% for v in stages %}<option {% if v==lead.stage %}selected{% endif %}>{{v}}</option>{% endfor %}</select></label>
<label>Next follow-up<input type="date" name="follow_up" value="{{lead.follow_up}}"></label></div><label>Notes<textarea name="note" rows="3" maxlength="4000">{{lead.note}}</textarea></label><button>Save changes</button></form></section>
{% else %}<p><a href="/">Return to prospects</a></p>{% endif %}
<footer>Discovery data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a></footer></main></body></html>""")


def page(title, view, status=200, **context):
    return HTMLResponse(TEMPLATE.render(title=title, view=view, stages=store.STAGES, **context),
                        status_code=status, headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer",
                        "Content-Security-Policy":"default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"})


def parsed_filters(request):
    return store.Filters(**{k:v for k,v in request.query_params.items() if k in store.Filters.model_fields and v})


def home(request):
    filters = parsed_filters(request)
    offset = int(request.query_params.get("offset",0))
    return page("Prospects","home", f=filters.model_dump(), results=store.search(filters,50,offset),
                lists=store.list_names(), offset=offset, qs=urlencode(filters.model_dump(exclude_none=True)),
                message=request.query_params.get("message",""))


def export(request):
    return Response(store.export_csv(parsed_filters(request)), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":'attachment; filename="prospects.csv"', "Cache-Control":"no-store"})


async def form_page(request):
    path = request.url.path
    lead_id = request.path_params.get("lead_id")
    if request.method == "GET":
        if lead_id is not None:
            lead = store.get_lead(lead_id)
            return page(lead["company"],"lead",lead=lead, message=request.query_params.get("message",""))
        return page("Discover businesses" if path=="/discover" else "Import leads",path[1:],categories=store.CATEGORIES)
    if request.headers.get("origin") != str(request.base_url).rstrip("/"):
        return PlainTextResponse("This form requires the local workspace origin.",status_code=403)
    if int(request.headers.get("content-length","0")) > 2_100_000:
        return PlainTextResponse("Import up to 2 MB per request",status_code=413)
    async with request.form(max_part_size=2_000_000) as form:
        destination = "/"
        if path == "/import":
            file = form.get("file")
            raw = (await file.read(2_000_001)).decode("utf-8-sig") if getattr(file,"filename",None) else form.get("text","")
            result = store.import_csv(raw)
        elif path == "/discover":
            result = await run_in_threadpool(store.discover, store.Area.model_validate(dict(form)))
        elif path == "/demo":
            result = store.import_csv(store.DEMO)
        elif path == "/shortlist":
            result = store.shortlist(form.get("name",""), [int(i) for i in form.getlist("ids")])
            return RedirectResponse("/?"+urlencode({"list_name":result["list_name"]}),303)
        else:
            store.update(lead_id, form["stage"],form["note"],form["follow_up"])
            return RedirectResponse(path+"?message=Changes+saved",303)
    message = f"{result['added']} added · {result['matched']} matched existing records"
    return RedirectResponse(destination+"?"+urlencode({"message":message}),303)


async def error(request, exc):
    return page("Check your input","error",400,message=str(exc))


app = Starlette(routes=[Route("/",home),Route("/export",export),
    *[Route(path,form_page,methods=["GET","POST"]) for path in ("/discover","/import","/lead/{lead_id:int}")],
    *[Route(path,form_page,methods=["POST"]) for path in ("/demo","/shortlist")]],
    exception_handlers={ValueError:error,csv.Error:error,KeyError:error})
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost","127.0.0.1"])
