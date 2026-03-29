import json
import re
import asyncio
import aiohttp
import hashlib
import logging
import os
import smtplib
import time
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from functools import wraps

# =============================================================================
#  STEP 1 — LOGGING SETUP
#  Replaces all print() with proper logging to console + file
# =============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# =============================================================================
#  STEP 2 — LOAD & VALIDATE CONFIG
#  Catches bad config before scraping starts
# =============================================================================
def load_config(path="ats_config.json"):
    with open(path, "r") as f:
        return json.load(f)

def validate_config(config):
    required_keys    = ["filters", "ats_sources"]
    required_filters = ["hours_limit", "keywords", "exclude_keywords"]
    required_ats     = [
        "name", "base_url", "title_field",
        "date_field", "location_field", "url_field", "date_format"
    ]
    errors = []

    for key in required_keys:
        if key not in config:
            errors.append(f"Missing top-level key: '{key}'")

    for key in required_filters:
        if key not in config.get("filters", {}):
            errors.append(f"Missing filter: '{key}'")

    for ats in config.get("ats_sources", []):
        name = ats.get("name", "?")
        for key in required_ats:
            if ats.get("fetch_type") == "workday_post":
                break          # workday uses different fields — skip generic check
            if key not in ats:
                errors.append(f"ATS '{name}' missing field: '{key}'")

    if errors:
        logger.error("Config validation failed:")
        for e in errors:
            logger.error(f"  - {e}")
        raise SystemExit(1)

    logger.info("Config validated successfully")


# =============================================================================
#  STEP 3 — DATE PARSERS
# =============================================================================
def parse_date(value, fmt):
    if not value:
        return None
    try:
        if fmt == "iso":
            return datetime.fromisoformat(
                str(value).replace("Z", "+00:00")
            ).astimezone(timezone.utc)
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


# =============================================================================
#  STEP 4 — NESTED FIELD GETTER
# =============================================================================
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


# =============================================================================
#  STEP 5 — JOB CATEGORY DETECTION
# =============================================================================
JAVA_KEYWORDS = [
    "java", "spring boot", "spring framework", "j2ee", "jvm",
    "java developer", "java engineer", "java full stack", "java backend"
]
PYTHON_KEYWORDS = [
    "python", "django", "flask", "fastapi", "python developer",
    "python engineer", "machine learning", "ml engineer",
    "data engineer", "data scientist", "pyspark"
]

def classify_job(title):
    """Returns 'Java', 'Python', or 'Software'. Java > Python > Software priority."""
    t = title.lower()
    if any(k in t for k in JAVA_KEYWORDS):
        return "Java"
    if any(k in t for k in PYTHON_KEYWORDS):
        return "Python"
    return "Software"


# =============================================================================
#  STEP 6 — USA LOCATION FILTER
# =============================================================================
NON_USA = [
    "india","canada","uk","united kingdom","germany","france","australia",
    "singapore","ireland","netherlands","spain","poland","brazil","mexico",
    "china","japan","korea","sweden","norway","denmark","finland","italy",
    "portugal","switzerland","austria","belgium","czech","hungary","romania",
    "ukraine","turkey","israel","uae","dubai","saudi","egypt","south africa",
    "philippines","indonesia","malaysia","thailand","vietnam","pakistan",
    "bangladesh","sri lanka","nepal","new zealand","argentina","colombia",
    "chile","peru","russia",
    "bangalore","bengaluru","hyderabad","mumbai","pune","chennai","delhi",
    "noida","gurgaon","gurugram","kolkata","ahmedabad","jaipur","kochi",
    "coimbatore","indore","bhopal","nagpur","surat","vadodara","lucknow",
    "chandigarh","bhubaneswar","thiruvananthapuram","visakhapatnam",
    "secunderabad","mysore","mangalore","hubli","belgaum","nashik",
    "toronto","vancouver","montreal","calgary","ottawa","edmonton","winnipeg",
    "ontario","quebec","british columbia","alberta","manitoba","nova scotia",
    "london","manchester","birmingham","glasgow","edinburgh","bristol",
    "leeds","liverpool","sheffield","cardiff","belfast",
    "berlin","munich","frankfurt","hamburg","paris","lyon","marseille",
    "amsterdam","rotterdam","brussels","zurich","geneva","vienna","stockholm",
    "oslo","copenhagen","helsinki","sydney","melbourne","brisbane","perth",
    "auckland","wellington","tel aviv","hong kong","taipei","shanghai",
    "beijing","tokyo","seoul","jakarta","kuala lumpur","bangkok","manila",
    "ho chi minh","karachi","lahore","dhaka","colombo","kathmandu",
    "cairo","lagos","nairobi","johannesburg"
]

USA_STATES = {
    "alabama":"Alabama","alaska":"Alaska","arizona":"Arizona",
    "arkansas":"Arkansas","california":"California","colorado":"Colorado",
    "connecticut":"Connecticut","delaware":"Delaware","florida":"Florida",
    "georgia":"Georgia","hawaii":"Hawaii","idaho":"Idaho",
    "illinois":"Illinois","indiana":"Indiana","iowa":"Iowa",
    "kansas":"Kansas","kentucky":"Kentucky","louisiana":"Louisiana",
    "maine":"Maine","maryland":"Maryland","massachusetts":"Massachusetts",
    "michigan":"Michigan","minnesota":"Minnesota","mississippi":"Mississippi",
    "missouri":"Missouri","montana":"Montana","nebraska":"Nebraska",
    "nevada":"Nevada","new hampshire":"New Hampshire","new jersey":"New Jersey",
    "new mexico":"New Mexico","new york":"New York",
    "north carolina":"North Carolina","north dakota":"North Dakota",
    "ohio":"Ohio","oklahoma":"Oklahoma","oregon":"Oregon",
    "pennsylvania":"Pennsylvania","rhode island":"Rhode Island",
    "south carolina":"South Carolina","south dakota":"South Dakota",
    "tennessee":"Tennessee","texas":"Texas","utah":"Utah",
    "vermont":"Vermont","virginia":"Virginia","washington":"Washington",
    "west virginia":"West Virginia","wisconsin":"Wisconsin","wyoming":"Wyoming",
    "district of columbia":"Washington DC","washington dc":"Washington DC",
    "washington d.c.":"Washington DC",
}

STATE_ABBR = {
    ", al":"Alabama",", ak":"Alaska",", az":"Arizona",", ar":"Arkansas",
    ", ca":"California",", co":"Colorado",", ct":"Connecticut",", de":"Delaware",
    ", fl":"Florida",", ga":"Georgia",", hi":"Hawaii",", id":"Idaho",
    ", il":"Illinois",", in":"Indiana",", ia":"Iowa",", ks":"Kansas",
    ", ky":"Kentucky",", la":"Louisiana",", me":"Maine",", md":"Maryland",
    ", ma":"Massachusetts",", mi":"Michigan",", mn":"Minnesota",
    ", ms":"Mississippi",", mo":"Missouri",", mt":"Montana",", ne":"Nebraska",
    ", nv":"Nevada",", nh":"New Hampshire",", nj":"New Jersey",
    ", nm":"New Mexico",", ny":"New York",", nc":"North Carolina",
    ", nd":"North Dakota",", oh":"Ohio",", ok":"Oklahoma",", or":"Oregon",
    ", pa":"Pennsylvania",", ri":"Rhode Island",", sc":"South Carolina",
    ", sd":"South Dakota",", tn":"Tennessee",", tx":"Texas",", ut":"Utah",
    ", vt":"Vermont",", va":"Virginia",", wa":"Washington",
    ", wv":"West Virginia",", wi":"Wisconsin",", wy":"Wyoming",
    ", dc":"Washington DC",
}

CITY_TO_STATE = {
    "new york city":"New York","nyc":"New York","manhattan":"New York",
    "brooklyn":"New York","queens":"New York","buffalo":"New York",
    "albany":"New York","rochester":"New York",
    "san francisco":"California","bay area":"California",
    "silicon valley":"California","san jose":"California",
    "los angeles":"California","santa monica":"California",
    "san diego":"California","la jolla":"California",
    "seattle":"Washington","bellevue":"Washington",
    "redmond":"Washington","kirkland":"Washington",
    "austin":"Texas","dallas":"Texas","houston":"Texas",
    "san antonio":"Texas","fort worth":"Texas",
    "chicago":"Illinois","naperville":"Illinois","evanston":"Illinois",
    "boston":"Massachusetts","cambridge":"Massachusetts",
    "somerville":"Massachusetts","waltham":"Massachusetts",
    "denver":"Colorado","boulder":"Colorado","colorado springs":"Colorado",
    "atlanta":"Georgia","alpharetta":"Georgia",
    "miami":"Florida","fort lauderdale":"Florida","boca raton":"Florida",
    "orlando":"Florida","tampa":"Florida","jacksonville":"Florida",
    "charlotte":"North Carolina","raleigh":"North Carolina","durham":"North Carolina",
    "phoenix":"Arizona","scottsdale":"Arizona","tempe":"Arizona","chandler":"Arizona",
    "philadelphia":"Pennsylvania","pittsburgh":"Pennsylvania",
    "minneapolis":"Minnesota","st paul":"Minnesota",
    "nashville":"Tennessee","memphis":"Tennessee","knoxville":"Tennessee",
    "portland":"Oregon","salt lake city":"Utah","provo":"Utah",
    "las vegas":"Nevada","reno":"Nevada",
    "detroit":"Michigan","ann arbor":"Michigan","grand rapids":"Michigan",
    "columbus":"Ohio","cleveland":"Ohio","cincinnati":"Ohio",
    "kansas city":"Missouri","st louis":"Missouri","saint louis":"Missouri",
    "indianapolis":"Indiana","louisville":"Kentucky","lexington":"Kentucky",
    "richmond":"Virginia","norfolk":"Virginia","virginia beach":"Virginia",
    "hartford":"Connecticut","new haven":"Connecticut","stamford":"Connecticut",
    "providence":"Rhode Island","albuquerque":"New Mexico","santa fe":"New Mexico",
    "omaha":"Nebraska","tulsa":"Oklahoma","oklahoma city":"Oklahoma",
    "boise":"Idaho","billings":"Montana","des moines":"Iowa",
    "madison":"Wisconsin","milwaukee":"Wisconsin","honolulu":"Hawaii",
    "anchorage":"Alaska",
}

USA_CONFIRMED = (
    list(STATE_ABBR.keys()) +
    list(USA_STATES.keys()) +
    list(CITY_TO_STATE.keys()) +
    [
        "united states","usa","u.s.a","u.s.",
        "remote - us","remote, us","remote (us","us remote",
        "remote - united states","remote, united states",
        "work from home - us","anywhere in the us",
        "new york, ny","sf bay","la, ca","portland, or","portland, oregon",
        "research triangle",
    ]
)

def is_usa_location(location):
    if not location or str(location).strip() in ("", "Not specified", "None", "null"):
        return False
    loc = str(location).lower().strip()
    if any(x in loc for x in NON_USA):
        return False
    if any(x in loc for x in USA_CONFIRMED):
        return True
    if loc.strip() in ("remote", "anywhere", "worldwide", "global", "work from home"):
        return False
    return False

def extract_state(location):
    if not location:
        return "Other USA"
    loc = location.lower().strip()
    remote_indicators = [
        "remote - us","remote, us","us remote","remote - united states",
        "remote, united states","work from home - us","anywhere in the us","remote (us",
    ]
    if any(r in loc for r in remote_indicators):
        return "Remote"
    if loc in ("remote", "work from home"):
        return "Remote"
    for name, state in USA_STATES.items():
        if name in loc:
            return state
    for city, state in CITY_TO_STATE.items():
        if city in loc:
            return state
    for abbr, state in STATE_ABBR.items():
        pattern = re.escape(abbr) + r'(?=[^a-z]|$)'
        if re.search(pattern, loc):
            return state
    return "Other USA"


# =============================================================================
#  STEP 7 — KEYWORD FILTER
# =============================================================================
def matches_keywords(title, include_kws, exclude_kws):
    t = title.lower()
    return (
        any(k in t for k in include_kws) and
        not any(k in t for k in exclude_kws)
    )


# =============================================================================
#  STEP 8 — DUPLICATE DETECTION ACROSS RUNS
#  Saves seen job hashes to disk so repeat jobs are skipped next run
# =============================================================================
SEEN_JOBS_FILE = "seen_jobs.json"

def load_seen_jobs():
    if os.path.exists(SEEN_JOBS_FILE):
        with open(SEEN_JOBS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen_jobs(seen):
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(list(seen), f)

def job_hash(job):
    """Unique fingerprint per job — title + company + url."""
    key = f"{job['title']}_{job['company']}_{job['apply_url']}"
    return hashlib.md5(key.encode()).hexdigest()

def filter_new_jobs(all_jobs, seen_jobs):
    new_jobs = []
    for job in all_jobs:
        h = job_hash(job)
        if h not in seen_jobs:
            new_jobs.append(job)
            seen_jobs.add(h)
    logger.info(
        f"Duplicate filter: {len(all_jobs)} total → "
        f"{len(new_jobs)} new | "
        f"{len(all_jobs) - len(new_jobs)} already seen"
    )
    return new_jobs


# =============================================================================
#  STEP 9 — JOB SCORING BY RELEVANCE
#  Scores jobs based on your preferences in config
# =============================================================================
def score_job(job, preferences):
    if not preferences:
        job["score"] = 0
        return job

    score = 0
    title = job["title"].lower()

    for skill in preferences.get("preferred_skills", []):
        if skill.lower() in title:
            score += 10

    if job.get("state") in preferences.get("preferred_states", []):
        score += 5

    if job.get("company") in preferences.get("preferred_companies", []):
        score += 8

    level = preferences.get("level", "")
    if level == "senior" and "senior" in title:
        score += 5
    if level == "junior" and ("junior" in title or "associate" in title):
        score += 5

    job["score"] = score
    return job


# =============================================================================
#  STEP 10 — RETRY DECORATOR
#  Retries failed requests up to 3 times with exponential backoff
# =============================================================================
def retry(max_attempts=3, delay=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                    if result is not None:
                        return result
                except Exception as e:
                    if attempt == max_attempts - 1:
                        logger.warning(
                            f"Failed after {max_attempts} attempts: {e}"
                        )
                        return None
                time.sleep(delay * (2 ** attempt))  # 2s, 4s, 8s
            return None
        return wrapper
    return decorator


# =============================================================================
#  STEP 11 — ASYNC FETCH STRATEGIES
#  Fetches all companies concurrently — ~10x faster than sequential
# =============================================================================
HEADERS = {"User-Agent": "Mozilla/5.0"}

@retry(max_attempts=3, delay=2)
def fetch_rest_get_sync(url):
    """Sync fallback for non-async paths."""
    import requests
    r = requests.get(url, timeout=12, headers=HEADERS)
    return r.json() if r.status_code == 200 else None

async def fetch_rest_get_async(session, url):
    """Async GET with retry."""
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=12)) as r:
                if r.status == 200:
                    return await r.json(content_type=None)
        except Exception as e:
            if attempt == 2:
                logger.warning(f"GET failed {url}: {e}")
            await asyncio.sleep(2 ** attempt)
    return None

async def fetch_graphql_async(session, url, query, company):
    payload = {
        "operationName": "ApiJobBoardWithTeams",
        "query": query,
        "variables": {"organizationHostedJobsPageName": company}
    }
    for attempt in range(3):
        try:
            async with session.post(
                url, json=payload,
                timeout=aiohttp.ClientTimeout(total=12),
                headers={"Content-Type": "application/json", **HEADERS}
            ) as r:
                if r.status == 200:
                    data = await r.json(content_type=None)
                    return (data.get("data", {})
                                .get("jobBoard", {})
                                .get("jobPostings", []))
        except Exception as e:
            if attempt == 2:
                logger.warning(f"GraphQL failed {url}: {e}")
            await asyncio.sleep(2 ** attempt)
    return None

async def fetch_workday_async(session, ats, company_obj, filters):
    """
    Workday uses POST with keyword search.
    Searches multiple keywords and deduplicates across them.
    """
    slug     = company_obj["slug"]
    instance = company_obj["instance"]
    site     = company_obj["site"]
    display  = company_obj["display"]
    url = (
        f"https://{slug}.wd{instance}.myworkdayjobs.com"
        f"/wday/cxs/{slug}/{site}/jobs"
    )

    all_matched = []
    seen_titles = set()

    for keyword in ["java", "software engineer", "backend", "python", "full stack"]:
        payload = {
            "appliedFacets": {},
            "limit": 20,
            "offset": 0,
            "searchText": keyword
        }
        for attempt in range(3):
            try:
                async with session.post(
                    url, json=payload,
                    timeout=aiohttp.ClientTimeout(total=12),
                    headers={"Content-Type": "application/json", **HEADERS}
                ) as r:
                    if r.status != 200:
                        break
                    data      = await r.json(content_type=None)
                    jobs_list = data.get("jobPostings", [])

                    for job in jobs_list:
                        title     = job.get("title", "")
                        date_raw  = job.get("postedOn", "")
                        location  = job.get("locationsText", "")
                        ext_path  = job.get("externalPath", "")
                        apply_url = (
                            f"https://{slug}.wd{instance}.myworkdayjobs.com{ext_path}"
                        )
                        posted_at = parse_date(date_raw, "iso")

                        if not is_within_hours(posted_at, filters["hours_limit"]): continue
                        if not matches_keywords(title, filters["keywords"],
                                                filters["exclude_keywords"]): continue
                        if not is_usa_location(str(location)): continue
                        if title in seen_titles: continue

                        seen_titles.add(title)
                        all_matched.append({
                            "category":  classify_job(title),
                            "title":     title,
                            "company":   display,
                            "ats":       "Workday",
                            "state":     extract_state(str(location)),
                            "location":  str(location),
                            "posted_at": (
                                posted_at.strftime("%Y-%m-%d %H:%M UTC")
                                if posted_at else "Unknown"
                            ),
                            "apply_url": apply_url,
                            "score":     0
                        })
                    break   # success — don't retry
            except Exception as e:
                if attempt == 2:
                    logger.warning(f"Workday failed {display} / {keyword}: {e}")
                await asyncio.sleep(2 ** attempt)

    return all_matched


# =============================================================================
#  STEP 12 — PAGINATION SUPPORT
#  Fetches ALL pages not just the first page (for REST APIs that support it)
# =============================================================================
async def fetch_paginated_async(session, base_url, jobs_key, page_size=50):
    all_jobs = []
    offset   = 0

    while True:
        sep = "&" if "?" in base_url else "?"
        url  = f"{base_url}{sep}limit={page_size}&offset={offset}"
        data = await fetch_rest_get_async(session, url)

        if not data:
            break

        jobs = data.get(jobs_key, []) if jobs_key else (
            data if isinstance(data, list) else []
        )
        if not jobs:
            break

        all_jobs.extend(jobs)

        if len(jobs) < page_size:
            break   # last page reached

        offset += page_size
        await asyncio.sleep(0.3)   # polite delay between pages

    return all_jobs


# =============================================================================
#  STEP 13 — PARSE RAW JOB LIST → FILTERED JOBS
# =============================================================================
def parse_jobs(jobs_list, ats, company_display, filters, preferences=None):
    matched = []
    for job in jobs_list:
        title     = get_field(job, ats["title_field"]) or ""
        date_raw  = get_field(job, ats["date_field"])
        location  = get_field(job, ats["location_field"]) or ""
        url       = get_field(job, ats["url_field"]) or ""
        posted_at = parse_date(date_raw, ats["date_format"])

        if not is_within_hours(posted_at, filters["hours_limit"]):         continue
        if not matches_keywords(title, filters["keywords"],
                                filters["exclude_keywords"]):              continue
        if not is_usa_location(str(location)):                             continue

        job_entry = {
            "category":  classify_job(title),
            "title":     title,
            "company":   company_display,
            "ats":       ats["name"],
            "state":     extract_state(str(location)),
            "location":  str(location),
            "posted_at": (
                posted_at.strftime("%Y-%m-%d %H:%M UTC") if posted_at else "Unknown"
            ),
            "apply_url": url,
            "score":     0
        }
        score_job(job_entry, preferences)
        matched.append(job_entry)

    return matched


# =============================================================================
#  STEP 14 — ASYNC MAIN FETCH ROUTER
#  Routes each company to the right fetch strategy concurrently
# =============================================================================
async def fetch_jobs_async(session, ats, company, filters, preferences=None):
    ftype = ats.get("fetch_type", "rest_get")

    if ftype == "workday_post":
        return await fetch_workday_async(session, ats, company, filters)

    company_slug    = company
    company_display = company.upper()

    if ftype == "graphql":
        jobs_list = await fetch_graphql_async(
            session, ats["base_url"], ats["graphql_query"], company_slug
        )
        if jobs_list is None:
            return []
        return parse_jobs(jobs_list, ats, company_display, filters, preferences)

    # REST GET — use pagination
    url = ats["base_url"].replace("{company}", company_slug)
    jobs_key = ats.get("jobs_key")

    if ats.get("paginated"):
        # Paginated REST — fetch all pages
        jobs_list = await fetch_paginated_async(session, url, jobs_key)
    else:
        # Single page REST
        data = await fetch_rest_get_async(session, url)
        if data is None:
            return []
        jobs_list = (
            data.get(jobs_key, []) if jobs_key
            else (data if isinstance(data, list) else [])
        )

    return parse_jobs(jobs_list, ats, company_display, filters, preferences)


async def run_all_fetches(config):
    """
    Runs all company fetches concurrently using asyncio.
    All companies fetched at the same time — massive speed improvement.
    """
    filters     = config["filters"]
    preferences = config.get("preferences")
    all_jobs    = []

    connector = aiohttp.TCPConnector(limit=20)   # max 20 concurrent connections
    async with aiohttp.ClientSession(
        connector=connector, headers=HEADERS
    ) as session:

        for ats in config["ats_sources"]:
            ats_name  = ats["name"]
            companies = ats["companies"]
            logger.info(f"[{ats_name}] — {len(companies)} companies (concurrent fetch)")

            # Create one task per company — all run at the same time
            tasks = [
                fetch_jobs_async(session, ats, company, filters, preferences)
                for company in companies
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for company, jobs in zip(companies, results):
                if isinstance(jobs, Exception):
                    logger.warning(f"  Error fetching {company}: {jobs}")
                    continue
                if not jobs:
                    jobs = []
                display = (
                    company["display"]
                    if isinstance(company, dict)
                    else company.upper()
                )
                logger.info(f"  {display:<30} {len(jobs)} found")
                all_jobs.extend(jobs)

    return all_jobs


# =============================================================================
#  STEP 15 — ORGANIZE: Category > State > Jobs
# =============================================================================
CATEGORIES = ["Java", "Python", "Software"]

def organize_jobs(all_jobs):
    result = {cat: {} for cat in CATEGORIES}

    for job in all_jobs:
        cat   = job.get("category", "Software")
        state = job.get("state") or "Other USA"
        result[cat].setdefault(state, []).append(job)

    # Sort jobs within each state by score descending
    for cat in CATEGORIES:
        for state in result[cat]:
            result[cat][state].sort(key=lambda x: x.get("score", 0), reverse=True)

    # Sort states: alpha → Other USA → Remote
    for cat in CATEGORIES:
        states = result[cat]
        sorted_states = sorted([
            s for s in states if s not in ("Remote", "Other USA")
        ])
        if "Other USA" in states:
            sorted_states.append("Other USA")
        if "Remote" in states:
            sorted_states.append("Remote")
        result[cat] = {s: states[s] for s in sorted_states}

    return result


# =============================================================================
#  STEP 16 — PRINT RESULTS
# =============================================================================
def print_results(organized):
    total = sum(
        len(jobs)
        for cat_data in organized.values()
        for jobs in cat_data.values()
    )
    print(f"\nJOB SCRAPER  |  USA ONLY  |  Last 24h")
    print(f"Run time   : {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"Total jobs : {total}")
    print("=" * 60)

    for cat in CATEGORIES:
        cat_jobs  = organized[cat]
        cat_total = sum(len(j) for j in cat_jobs.values())
        if cat_total == 0:
            continue
        print(f"\n{'=' * 60}")
        print(f"  CATEGORY: {cat} ({cat_total} jobs)")
        print(f"{'=' * 60}")

        for state, jobs in cat_jobs.items():
            print(f"\n  [{state}] - {len(jobs)} job(s)")
            print(f"  {'-' * 56}")
            for i, job in enumerate(jobs, 1):
                score_label = f" [score: {job['score']}]" if job.get("score") else ""
                print(f"    {i}. {job['title']}{score_label}")
                print(f"       Company  : {job['company']}")
                print(f"       Location : {job['location']}")
                print(f"       Posted   : {job['posted_at']}")
                print(f"       Apply    : {job['apply_url']}")
                print()

def print_summary(organized):
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    grand_total = 0
    for cat in CATEGORIES:
        cat_jobs  = organized[cat]
        cat_total = sum(len(j) for j in cat_jobs.values())
        if cat_total == 0:
            continue
        print(f"\n  {cat} ({cat_total} total)")
        print(f"  {'State':<25} {'Jobs'}")
        print(f"  {'-' * 35}")
        for state, jobs in cat_jobs.items():
            print(f"  {state:<25} {len(jobs)}")
        grand_total += cat_total

    print("\n" + "-" * 40)
    print(f"  GRAND TOTAL                  {grand_total}")
    print("=" * 60)


# =============================================================================
#  STEP 17 — EMAIL NOTIFICATION
#  Sends email when new jobs are found (configure in ats_config.json)
# =============================================================================
def send_email_notification(new_jobs, config):
    email_cfg = config.get("email")
    if not email_cfg or not new_jobs:
        return

    body = (
        f"Found {len(new_jobs)} new USA Java/Python/SWE jobs!\n"
        f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
    )

    for job in new_jobs[:30]:   # cap at 30 in email
        body += f"{'=' * 50}\n"
        body += f"Title    : {job['title']}\n"
        body += f"Company  : {job['company']}\n"
        body += f"Category : {job['category']}\n"
        body += f"State    : {job['state']}\n"
        body += f"Score    : {job.get('score', 0)}\n"
        body += f"Posted   : {job['posted_at']}\n"
        body += f"Apply    : {job['apply_url']}\n\n"

    msg             = MIMEMultipart()
    msg["From"]     = email_cfg["sender"]
    msg["To"]       = email_cfg["recipient"]
    msg["Subject"]  = (
        f"{len(new_jobs)} New Jobs — "
        f"{datetime.now().strftime('%Y-%m-%d')}"
    )
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_cfg["sender"], email_cfg["password"])
            server.send_message(msg)
        logger.info(f"Email sent to {email_cfg['recipient']}")
    except Exception as e:
        logger.warning(f"Email failed: {e}")


# =============================================================================
#  STEP 18 — SAVE OUTPUT JSON
# =============================================================================
def save_output(organized, all_new_jobs):
    sorted_jobs = []
    for cat in CATEGORIES:
        for state, jobs in organized[cat].items():
            sorted_jobs.extend(jobs)

    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M UTC"),
        "total_jobs":   len(sorted_jobs),
        "by_category":  {
            cat: {
                "total":    sum(len(j) for j in organized[cat].values()),
                "by_state": organized[cat]
            }
            for cat in CATEGORIES
        },
        "all_jobs": sorted_jobs
    }

    with open("jobs_output.json", "w") as f:
        json.dump(output, f, indent=2)

    logger.info(f"Saved to jobs_output.json ({len(sorted_jobs)} new USA jobs)")


# =============================================================================
#  MAIN
# =============================================================================
async def main_async():
    logger.info("Job scraper starting...")
    logger.info(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Step 1 — Load and validate config
    config = load_config("ats_config.json")
    validate_config(config)

    # Step 2 — Load previously seen jobs (duplicate detection)
    seen_jobs = load_seen_jobs()
    logger.info(f"Loaded {len(seen_jobs)} previously seen job hashes")

    # Step 3 — Fetch all jobs concurrently (async)
    start    = time.time()
    all_jobs = await run_all_fetches(config)
    elapsed  = time.time() - start
    logger.info(f"Fetched {len(all_jobs)} total jobs in {elapsed:.1f}s")

    # Step 4 — Score jobs by preference
    preferences = config.get("preferences")
    if preferences:
        all_jobs = [score_job(j, preferences) for j in all_jobs]
        logger.info("Jobs scored by preference")

    # Step 5 — Filter out already seen jobs
    new_jobs = filter_new_jobs(all_jobs, seen_jobs)

    # Step 6 — Organize by category and state
    organized = organize_jobs(new_jobs)

    # Step 7 — Print to console
    print_results(organized)
    print_summary(organized)

    # Step 8 — Save seen jobs back to disk
    save_seen_jobs(seen_jobs)

    # Step 9 — Save output JSON
    save_output(organized, new_jobs)

    # Step 10 — Send email notification
    send_email_notification(new_jobs, config)

    logger.info("Done!")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()


# =============================================================================
#  SAMPLE ats_config.json structure (add to your config file):
# =============================================================================
# {
#   "filters": {
#     "hours_limit": 24,
#     "keywords": ["java", "python", "software engineer", "backend", "full stack"],
#     "exclude_keywords": ["manager", "director", "vp", "qa", "ios", "android"]
#   },
#   "preferences": {
#     "preferred_skills": ["spring boot", "kafka", "microservices"],
#     "preferred_states": ["California", "Texas", "Remote"],
#     "preferred_companies": ["GOOGLE", "AMAZON", "MICROSOFT"],
#     "level": "senior"
#   },
#   "email": {
#     "sender": "you@gmail.com",
#     "password": "your_gmail_app_password",
#     "recipient": "you@gmail.com"
#   },
#   "ats_sources": [
#     {
#       "name": "Greenhouse",
#       "fetch_type": "rest_get",
#       "paginated": false,
#       "base_url": "https://boards-api.greenhouse.io/v1/boards/{company}/jobs",
#       "jobs_key": "jobs",
#       "title_field": "title",
#       "date_field": "updated_at",
#       "location_field": "location.name",
#       "url_field": "absolute_url",
#       "date_format": "iso",
#       "companies": ["google", "stripe", "airbnb"]
#     }
#   ]
# }
