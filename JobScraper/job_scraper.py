import json
import requests
from datetime import datetime, timezone, timedelta
import time

# ─────────────────────────────────────────
#  LOAD CONFIG
# ─────────────────────────────────────────
def load_config(path="ats_config.json"):
    with open(path, "r") as f:
        return json.load(f)

# ─────────────────────────────────────────
#  DATE PARSERS
# ─────────────────────────────────────────
def parse_date(value, fmt):
    if not value:
        return None
    try:
        if fmt == "iso":
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
        elif fmt == "unix_ms":
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        elif fmt == "unix_s":
            return datetime.fromtimestamp(value, tz=timezone.utc)
    except Exception:
        return None

def is_within_hours(dt, hours):
    if dt is None:
        return False
    return dt >= datetime.now(timezone.utc) - timedelta(hours=hours)

# ─────────────────────────────────────────
#  NESTED FIELD GETTER
# ─────────────────────────────────────────
def get_field(obj, dotted_key):
    if not dotted_key:
        return None
    val = obj
    for k in dotted_key.split("."):
        if isinstance(val, dict):
            val = val.get(k)
        else:
            return None
    return val

# ─────────────────────────────────────────
#  USA LOCATION FILTER  ← FIXED
# ─────────────────────────────────────────

# Step 1: If ANY of these appear → REJECT immediately
NON_USA = [
    # Countries
    "india","canada","uk","united kingdom","germany","france","australia",
    "singapore","ireland","netherlands","spain","poland","brazil","mexico",
    "china","japan","korea","sweden","norway","denmark","finland","italy",
    "portugal","switzerland","austria","belgium","czech","hungary","romania",
    "ukraine","turkey","israel","uae","dubai","saudi","egypt","south africa",
    "philippines","indonesia","malaysia","thailand","vietnam","pakistan",
    "bangladesh","sri lanka","nepal","new zealand","argentina","colombia",
    "chile","peru","russia","ukraine",
    # Indian cities (very comprehensive)
    "bangalore","bengaluru","hyderabad","mumbai","pune","chennai","delhi",
    "noida","gurgaon","gurugram","kolkata","ahmedabad","jaipur","kochi",
    "coimbatore","indore","bhopal","nagpur","surat","vadodara","lucknow",
    "chandigarh","bhubaneswar","thiruvananthapuram","visakhapatnam",
    "secunderabad","mysore","mangalore","hubli","belgaum","nashik",
    # Canadian cities
    "toronto","vancouver","montreal","calgary","ottawa","edmonton","winnipeg",
    "ontario","quebec","british columbia","alberta","manitoba","nova scotia",
    # UK cities
    "london","manchester","birmingham","glasgow","edinburgh","bristol",
    "leeds","liverpool","sheffield","cardiff","belfast",
    # Other major non-US cities
    "berlin","munich","frankfurt","hamburg","paris","lyon","marseille",
    "amsterdam","rotterdam","brussels","zurich","geneva","vienna","stockholm",
    "oslo","copenhagen","helsinki","sydney","melbourne","brisbane","perth",
    "auckland","wellington","toronto","tel aviv","dubai","singapore city",
    "hong kong","taipei","shanghai","beijing","tokyo","seoul","jakarta",
    "kuala lumpur","bangkok","manila","ho chi minh","karachi","lahore",
    "dhaka","colombo","kathmandu","cairo","lagos","nairobi","johannesburg"
]

# Step 2: If ANY of these appear → ACCEPT as USA
USA_CONFIRMED = [
    # Country identifiers
    "united states", "usa", "u.s.a", "u.s.",
    # USA Remote variations
    "remote - us", "remote, us", "remote (us", "us remote",
    "remote - united states", "remote, united states",
    "work from home - us", "anywhere in the us",
    # States (full names)
    "alabama","alaska","arizona","arkansas","california","colorado",
    "connecticut","delaware","florida","georgia","hawaii","idaho",
    "illinois","indiana","iowa","kansas","kentucky","louisiana","maine",
    "maryland","massachusetts","michigan","minnesota","mississippi",
    "missouri","montana","nebraska","nevada","new hampshire","new jersey",
    "new mexico","new york","north carolina","north dakota","ohio",
    "oklahoma","oregon","pennsylvania","rhode island","south carolina",
    "south dakota","tennessee","texas","utah","vermont","virginia",
    "washington","west virginia","wisconsin","wyoming",
    "district of columbia","washington dc","washington d.c.",
    # State abbreviations (with comma or space to avoid false matches)
    ", al", ", ak", ", az", ", ar", ", ca", ", co", ", ct", ", de",
    ", fl", ", ga", ", hi", ", id", ", il", ", in", ", ia", ", ks",
    ", ky", ", la", ", me", ", md", ", ma", ", mi", ", mn", ", ms",
    ", mo", ", mt", ", ne", ", nv", ", nh", ", nj", ", nm", ", ny",
    ", nc", ", nd", ", oh", ", ok", ", or", ", pa", ", ri", ", sc",
    ", sd", ", tn", ", tx", ", ut", ", vt", ", va", ", wa", ", wv",
    ", wi", ", wy", ", dc",
    # Major US cities
    "new york city","new york, ny","nyc","manhattan","brooklyn","queens",
    "san francisco","sf bay","bay area","silicon valley","san jose",
    "los angeles","la, ca","santa monica","west hollywood",
    "seattle","bellevue","redmond","kirkland",
    "austin","dallas","houston","san antonio","fort worth",
    "chicago","naperville","evanston",
    "boston","cambridge, ma","somerville","waltham",
    "denver","boulder","colorado springs",
    "atlanta","alpharetta","buckhead",
    "miami","fort lauderdale","boca raton","orlando","tampa","jacksonville",
    "charlotte","raleigh","durham","research triangle",
    "phoenix","scottsdale","tempe","chandler",
    "philadelphia","pittsburgh",
    "minneapolis","st paul","twin cities",
    "nashville","memphis","knoxville",
    "portland, or","portland, oregon",
    "salt lake city","provo","utah",
    "las vegas","reno",
    "san diego","la jolla",
    "detroit","ann arbor","grand rapids",
    "columbus, oh","cleveland","cincinnati",
    "kansas city","st louis","saint louis",
    "indianapolis","fort wayne",
    "louisville","lexington",
    "richmond, va","norfolk","virginia beach",
    "hartford","new haven","stamford",
    "providence, ri","worcester",
    "albany, ny","buffalo, ny","rochester, ny",
    "albuquerque","santa fe",
    "omaha","lincoln, ne",
    "tulsa","oklahoma city",
    "little rock","fayetteville, ar",
    "boise","idaho falls",
    "billings","missoula",
    "des moines","iowa city",
    "madison, wi","milwaukee","green bay",
    "honolulu","anchorage"
]

def is_usa_location(location):
    """
    STRICT 3-step filter:
    1. Blank/null  → REJECT (many Indian remote jobs have blank location)
    2. Non-USA match → REJECT
    3. USA match → ACCEPT
    4. No match either way → REJECT (strict default)
    """
    # Step 1: blank = reject (changed from accept!)
    if not location or str(location).strip() in ("", "Not specified", "None", "null"):
        return False

    loc = str(location).lower().strip()

    # Step 2: non-USA match → reject immediately
    if any(x in loc for x in NON_USA):
        return False

    # Step 3: confirmed USA → accept
    if any(x in loc for x in USA_CONFIRMED):
        return True

    # Step 4: plain "remote" with no country context → REJECT
    # (too risky — could be India remote)
    if loc.strip() in ("remote", "anywhere", "worldwide", "global", "work from home"):
        return False

    # Step 5: unknown location → REJECT (strict)
    return False

# ─────────────────────────────────────────
#  KEYWORD FILTER
# ─────────────────────────────────────────
def matches_keywords(title, include_kws, exclude_kws):
    t = title.lower()
    return any(k in t for k in include_kws) and not any(k in t for k in exclude_kws)

# ─────────────────────────────────────────
#  PARSE RAW JOB LIST → FILTERED JOBS
# ─────────────────────────────────────────
def parse_jobs(jobs_list, ats, company_display, filters):
    matched = []
    for job in jobs_list:
        title     = get_field(job, ats["title_field"]) or ""
        date_raw  = get_field(job, ats["date_field"])
        location  = get_field(job, ats["location_field"]) or ""
        url       = get_field(job, ats["url_field"]) or ""
        posted_at = parse_date(date_raw, ats["date_format"])

        if not is_within_hours(posted_at, filters["hours_limit"]):  continue
        if not matches_keywords(title, filters["keywords"], filters["exclude_keywords"]): continue
        if not is_usa_location(str(location)): continue

        matched.append({
            "title":     title,
            "company":   company_display,
            "ats":       ats["name"],
            "location":  str(location),
            "posted_at": posted_at.strftime("%Y-%m-%d %H:%M UTC") if posted_at else "Unknown",
            "apply_url": url
        })
    return matched

# ─────────────────────────────────────────
#  FETCH STRATEGIES
# ─────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0"}

def fetch_rest_get(url):
    try:
        r = requests.get(url, timeout=12, headers=HEADERS)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None

def fetch_graphql(url, query, company):
    try:
        payload = {
            "operationName": "ApiJobBoardWithTeams",
            "query": query,
            "variables": {"organizationHostedJobsPageName": company}
        }
        r = requests.post(url, json=payload, timeout=12,
                          headers={"Content-Type": "application/json", **HEADERS})
        if r.status_code != 200:
            return None
        return (r.json().get("data", {})
                        .get("jobBoard", {})
                        .get("jobPostings", []))
    except Exception:
        return None

def fetch_workday(ats, company_obj, filters):
    slug     = company_obj["slug"]
    instance = company_obj["instance"]
    site     = company_obj["site"]
    display  = company_obj["display"]
    url = (f"https://{slug}.wd{instance}.myworkdayjobs.com"
           f"/wday/cxs/{slug}/{site}/jobs")

    all_matched = []
    seen_titles = set()

    for keyword in ["java", "software engineer", "backend", "python", "full stack"]:
        payload = {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": keyword}
        try:
            r = requests.post(url, json=payload, timeout=12,
                              headers={"Content-Type": "application/json", **HEADERS})
            if r.status_code != 200:
                continue
            jobs_list = r.json().get("jobPostings", [])
            for job in jobs_list:
                title     = job.get("title", "")
                date_raw  = job.get("postedOn", "")
                location  = job.get("locationsText", "")
                ext_path  = job.get("externalPath", "")
                apply_url = f"https://{slug}.wd{instance}.myworkdayjobs.com{ext_path}"
                posted_at = parse_date(date_raw, "iso")

                if not is_within_hours(posted_at, filters["hours_limit"]): continue
                if not matches_keywords(title, filters["keywords"], filters["exclude_keywords"]): continue
                if not is_usa_location(str(location)): continue
                if title in seen_titles: continue   # dedupe across keyword searches

                seen_titles.add(title)
                all_matched.append({
                    "title":     title,
                    "company":   display,
                    "ats":       "Workday",
                    "location":  str(location),
                    "posted_at": posted_at.strftime("%Y-%m-%d %H:%M UTC") if posted_at else "Unknown",
                    "apply_url": apply_url
                })
        except Exception:
            continue
    return all_matched

# ─────────────────────────────────────────
#  MAIN FETCH ROUTER
# ─────────────────────────────────────────
def fetch_jobs(ats, company, filters):
    ftype = ats.get("fetch_type", "rest_get")

    if ftype == "workday_post":
        return fetch_workday(ats, company, filters)

    company_slug    = company
    company_display = company.upper()

    if ftype == "graphql":
        jobs_list = fetch_graphql(ats["base_url"], ats["graphql_query"], company_slug)
        if jobs_list is None:
            return []
        return parse_jobs(jobs_list, ats, company_display, filters)

    url  = ats["base_url"].replace("{company}", company_slug)
    data = fetch_rest_get(url)
    if data is None:
        return []
    jobs_key  = ats.get("jobs_key")
    jobs_list = data.get(jobs_key, []) if jobs_key else (data if isinstance(data, list) else [])
    return parse_jobs(jobs_list, ats, company_display, filters)

# ─────────────────────────────────────────
#  DISPLAY
# ─────────────────────────────────────────
def print_company_block(company, ats_name, jobs):
    print(f"\n  ╔{'─'*64}╗")
    print(f"  ║  🏢  {company:<28} [{ats_name}]  —  {len(jobs)} job(s)")
    print(f"  ╚{'─'*64}╝")
    for i, job in enumerate(jobs, 1):
        print(f"\n    #{i}")
        print(f"    📌 {job['title']}")
        print(f"    📍 {job['location']}")
        print(f"    🕐 {job['posted_at']}")
        print(f"    🔗 {job['apply_url']}")
    print()

def print_summary(results):
    print("\n" + "═"*70)
    print("  📊  COMPANY-WISE SUMMARY  (USA ONLY | Last 24h | Java/Python/SWE)")
    print("═"*70)
    print(f"  {'#':<4}{'Company':<30}{'ATS':<16}{'Jobs'}")
    print("  " + "─"*58)
    total = 0
    idx   = 0
    for (company, ats_name), jobs in sorted(results.items(), key=lambda x: -len(x[1])):
        if not jobs: continue
        idx   += 1
        total += len(jobs)
        print(f"  {idx:<4}{company:<30}{ats_name:<16}✅ {len(jobs)}")
    print("  " + "─"*58)
    print(f"  {'TOTAL USA JOBS':<50}{total}")
    print("═"*70)

# ─────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────
def main():
    config  = load_config("ats_config.json")
    filters = config["filters"]
    hours   = filters["hours_limit"]

    print("\n" + "═"*70)
    print("  🚀  JOB SCRAPER  —  7 ATS  |  🇺🇸 USA ONLY  |  Last 24h")
    print(f"  ⏰  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("═"*70)

    results  = {}
    all_jobs = []

    for ats in config["ats_sources"]:
        ats_name  = ats["name"]
        companies = ats["companies"]
        print(f"\n\n{'▓'*70}")
        print(f"  📡  [{ats_name.upper()}]  —  {len(companies)} companies")
        print(f"{'▓'*70}")

        for company in companies:
            if isinstance(company, dict):
                display = company["display"]
                key     = display
            else:
                display = company.upper()
                key     = display

            print(f"  🔄  {key:<30}", end=" ", flush=True)
            jobs = fetch_jobs(ats, company, filters)
            all_jobs.extend(jobs)
            results[(key, ats_name)] = jobs
            print(f"✅ {len(jobs)} found" if jobs else "⬜ none")
            time.sleep(0.4)

    print("\n\n" + "═"*70)
    print("  📋  DETAILED RESULTS — COMPANY BY COMPANY  (USA Only)")
    print("═"*70)
    found_any = False
    for (company, ats_name), jobs in sorted(results.items(), key=lambda x: -len(x[1])):
        if jobs:
            found_any = True
            print_company_block(company, ats_name, jobs)
    if not found_any:
        print("\n  ⚠️  No USA Java/SWE jobs found in last 24h.")
        print("  💡  Try increasing hours_limit to 48 in ats_config.json\n")

    print_summary(results)

    with open("jobs_output.json", "w") as f:
        json.dump(all_jobs, f, indent=2)

    print(f"\n  💾  Saved → jobs_output.json  ({len(all_jobs)} USA jobs)")
    print("═"*70 + "\n")

if __name__ == "__main__":
    main()