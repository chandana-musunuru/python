import requests
import json
import time
from datetime import datetime
from urllib.parse import quote

# ─────────────────────────────────────────
#  CLOSED ATS COMPANIES CONFIG
#  These companies cannot be accessed via
#  public API — we search Google instead
# ─────────────────────────────────────────

CLOSED_ATS_COMPANIES = {

    "Taleo": [
        {"name": "Cognizant",        "site": "cognizant.taleo.net"},
        {"name": "Oracle",           "site": "oracle.taleo.net"},
        {"name": "Ford",             "site": "ford.taleo.net"},
        {"name": "General Motors",   "site": "gm.taleo.net"},
        {"name": "AT&T",             "site": "att.taleo.net"},
        {"name": "Humana",           "site": "humana.taleo.net"},
        {"name": "Lockheed Martin",  "site": "lmt.taleo.net"},
        {"name": "Boeing",           "site": "boeing.taleo.net"},
        {"name": "Deloitte",         "site": "deloitte.taleo.net"},
        {"name": "PwC",              "site": "pwc.taleo.net"},
        {"name": "KPMG",             "site": "kpmg.taleo.net"},
        {"name": "Cummins",          "site": "cummins.taleo.net"},
    ],

    "iCIMS": [
        {"name": "UnitedHealth",     "site": "careers.unitedhealthgroup.icims.com"},
        {"name": "FedEx",            "site": "careers.fedex.icims.com"},
        {"name": "UPS",              "site": "careers.ups.icims.com"},
        {"name": "Nvidia",           "site": "nvidia.icims.com"},
        {"name": "Target",           "site": "target.icims.com"},
        {"name": "EY",               "site": "eyglobal.icims.com"},
        {"name": "CVS Health",       "site": "jobs.cvshealth.com"},
        {"name": "Cigna",            "site": "cigna.icims.com"},
        {"name": "NCR",              "site": "ncr.icims.com"},
        {"name": "Fiserv",           "site": "fiserv.icims.com"},
        {"name": "General Mills",    "site": "generalmills.icims.com"},
        {"name": "Textron",          "site": "textron.icims.com"},
    ],

    "Custom Portal": [
        {"name": "Google",           "site": "careers.google.com",           "search_path": "/jobs/results/?q="},
        {"name": "Meta",             "site": "metacareers.com",               "search_path": "/jobs/?q="},
        {"name": "Apple",            "site": "jobs.apple.com",               "search_path": "/search#q="},
        {"name": "Microsoft",        "site": "careers.microsoft.com",        "search_path": "/en/jobs/search/?q="},
        {"name": "Netflix",          "site": "jobs.netflix.com",             "search_path": "/search?q="},
        {"name": "Uber",             "site": "www.uber.com/global/en/careers","search_path": "/jobs/?q="},
        {"name": "Spotify",          "site": "lifeatspotify.com",            "search_path": "/jobs/?q="},
        {"name": "Twitter/X",        "site": "careers.x.com",               "search_path": "/?q="},
        {"name": "LinkedIn",         "site": "careers.linkedin.com",         "search_path": "/jobs?q="},
        {"name": "Snap",             "site": "careers.snap.com",             "search_path": "/?q="},
        {"name": "Pinterest",        "site": "careers.pinterest.com",        "search_path": "/?q="},
        {"name": "Amazon",           "site": "amazon.jobs",                  "search_path": "/content/amzn/en_US/search.html#q="},
        {"name": "IBM",              "site": "ibm.com/careers",              "search_path": "/details?q="},
        {"name": "Wipro",            "site": "careers.wipro.com",            "search_path": "/?q="},
    ],

    "SAP SuccessFactors": [
        {"name": "SAP",              "site": "jobs.sap.com"},
        {"name": "Siemens",          "site": "siemens.com/careers"},
        {"name": "Nestle",           "site": "nestle.com/jobs"},
        {"name": "Honeywell",        "site": "careers.honeywell.com"},
        {"name": "3M",               "site": "3m.com/careers"},
        {"name": "P&G",              "site": "pgcareers.com"},
    ]
}

KEYWORDS = ["java", "software engineer", "backend", "python", "spring boot", "full stack"]

# ─────────────────────────────────────────
#  GOOGLE SEARCH — FREE (no API key needed)
#  Uses Google's public search with site: operator
# ─────────────────────────────────────────

def google_search_jobs(company_name, site, keyword, days_back=1):
    """
    Search Google for: site:[company_site] [keyword] java
    Filters to past N days using Google's date filter
    """
    # Build Google search URL
    query = f'site:{site} "{keyword}" software engineer OR java OR python OR backend'
    encoded = quote(query)
    
    # tbs=qdr:d = past day, qdr:w = past week
    time_filter = "qdr:d" if days_back <= 1 else f"qdr:d{days_back}"
    
    url = f"https://www.google.com/search?q={encoded}&tbs={time_filter}&num=10"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            # Parse job links from Google results
            results = parse_google_results(r.text, site, company_name)
            return results
        elif r.status_code == 429:
            print(f"      ⚠️  Google rate limited — wait 60s")
            time.sleep(60)
        return []
    except Exception as e:
        return []

def parse_google_results(html, site, company_name):
    """Extract job URLs and titles from Google search HTML"""
    from html.parser import HTMLParser
    
    results = []
    lines = html.split('\n')
    
    # Simple extraction — look for href links pointing to the target site
    import re
    
    # Find all URLs in the page that match our site
    url_pattern = re.compile(r'href="(https?://' + re.escape(site.replace('www.','')) + r'[^"]*)"')
    title_pattern = re.compile(r'<h3[^>]*>([^<]+)</h3>')
    
    urls   = url_pattern.findall(html)
    titles = title_pattern.findall(html)
    
    seen = set()
    for i, url in enumerate(urls[:5]):  # top 5 results
        if url in seen:
            continue
        seen.add(url)
        title = titles[i] if i < len(titles) else "Job Opening"
        # Clean HTML entities
        title = title.replace('&#39;', "'").replace('&amp;', '&').replace('&quot;', '"')
        results.append({
            "title":     title,
            "company":   company_name,
            "ats":       "Manual Search",
            "location":  "USA (verify on site)",
            "posted_at": "Within last 24h (Google filtered)",
            "apply_url": url,
            "note":      "⚠️ Verify posting date on company site"
        })
    
    return results

# ─────────────────────────────────────────
#  DIRECT CAREER PAGE LINKS
#  For when you just want the direct search URL
#  to click and search manually
# ─────────────────────────────────────────

def generate_direct_search_links():
    """
    Generate ready-to-click search URLs for each company
    These open directly on their careers page filtered by Java
    """
    links = []
    
    direct_searches = [
        # Taleo companies
        {
            "company": "Cognizant",
            "ats": "Taleo",
            "url": "https://cognizant.taleo.net/careersection/Lateral/jobsearch.ftl?lang=en&keyword=java+software+engineer"
        },
        {
            "company": "Oracle",
            "ats": "Taleo",
            "url": "https://oracle.taleo.net/careersection/2/jobsearch.ftl?lang=en&keyword=java+developer"
        },
        {
            "company": "Ford",
            "ats": "Taleo",
            "url": "https://ford.taleo.net/careersection/Ford_SN/jobsearch.ftl?lang=en&keyword=java"
        },
        # iCIMS companies
        {
            "company": "UnitedHealth/Optum",
            "ats": "iCIMS",
            "url": "https://careers.unitedhealthgroup.com/job-search-results/?keyword=java+software+engineer&location=United+States"
        },
        {
            "company": "FedEx",
            "ats": "iCIMS",
            "url": "https://careers.fedex.com/fedex/jobs?keywords=java+developer&location=United+States"
        },
        {
            "company": "Nvidia",
            "ats": "iCIMS",
            "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite?q=java+software+engineer"
        },
        # Custom ATS
        {
            "company": "Google",
            "ats": "Custom",
            "url": "https://careers.google.com/jobs/results/?q=java+software+engineer&location=United+States"
        },
        {
            "company": "Meta",
            "ats": "Custom",
            "url": "https://www.metacareers.com/jobs?q=java+software+engineer&locations%5B0%5D=United+States"
        },
        {
            "company": "Apple",
            "ats": "Custom",
            "url": "https://jobs.apple.com/en-us/search?search=java+software+engineer&sort=newest&location=united-states-USA"
        },
        {
            "company": "Microsoft",
            "ats": "Custom",
            "url": "https://careers.microsoft.com/global/en/search-results?q=java+software+engineer&lc=United+States"
        },
        {
            "company": "Amazon",
            "ats": "Custom",
            "url": "https://www.amazon.jobs/en-us/search?base_query=java+software+engineer&loc_query=United+States"
        },
        {
            "company": "IBM",
            "ats": "Custom",
            "url": "https://www.ibm.com/careers/search?field_keyword_08[0]=Software+Engineering&field_keyword_05[0]=Java"
        },
        {
            "company": "Netflix",
            "ats": "Custom",
            "url": "https://jobs.netflix.com/search?q=java+software+engineer"
        },
        {
            "company": "Uber",
            "ats": "Custom",
            "url": "https://www.uber.com/global/en/careers/list/?query=java+backend+engineer"
        },
        {
            "company": "Wipro",
            "ats": "Custom",
            "url": "https://careers.wipro.com/search/?searchby=title&q=java+developer&location=United+States"
        },
        # Banking
        {
            "company": "JP Morgan",
            "ats": "Workday",
            "url": "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/requisitions?keyword=java+software+engineer&location=United+States"
        },
        {
            "company": "Goldman Sachs",
            "ats": "Workday",
            "url": "https://www.goldmansachs.com/careers/search.html#/experience=Experienced+Professionals&skill=Java&location=United+States"
        },
        {
            "company": "Morgan Stanley",
            "ats": "Custom",
            "url": "https://www.morganstanley.com/careers/career-opportunities-search#q=java&t=1&ac=job_type_full_time&d=0"
        },
        {
            "company": "Citi",
            "ats": "Custom",
            "url": "https://jobs.citi.com/search-jobs/java%20software%20engineer/287/1?orgIds=287&kt=1"
        },
        {
            "company": "BlackRock",
            "ats": "Custom",
            "url": "https://careers.blackrock.com/job-search-results/?keyword=java+engineer&country=United+States+of+America"
        },
        {
            "company": "Vanguard",
            "ats": "Custom",
            "url": "https://www.vanguardjobs.com/search-jobs/java/13935/1"
        },
        # Healthcare
        {
            "company": "Epic Systems",
            "ats": "Custom",
            "url": "https://epic.com/careers#search=java"
        },
        {
            "company": "Cerner/Oracle Health",
            "ats": "Custom",
            "url": "https://www.oracle.com/careers/?q=java+cerner"
        },
        # Indian IT (US offices)
        {
            "company": "HCL America",
            "ats": "Custom",
            "url": "https://www.hcltech.com/careers/search-jobs?keyword=java+developer&location=United+States"
        },
        {
            "company": "LTIMindtree",
            "ats": "Custom",
            "url": "https://www.ltimindtree.com/careers/job-search/?search=java+developer&location=USA"
        },
        {
            "company": "Mphasis",
            "ats": "Custom",
            "url": "https://careers.mphasis.com/search/?searchby=title&q=java&locationCodes=US"
        },
        {
            "company": "Tech Mahindra",
            "ats": "Custom",
            "url": "https://careers.techmahindra.com/search/?q=java+developer&location=United+States"
        },
        # Staffing
        {
            "company": "Revature",
            "ats": "Custom",
            "url": "https://revature.com/find-a-job/?search=java"
        },
        {
            "company": "EPAM",
            "ats": "Custom",
            "url": "https://www.epam.com/careers/job-listings?search=java+developer&location=United+States"
        },
        {
            "company": "Collabera",
            "ats": "Custom",
            "url": "https://www.collabera.com/find-jobs/?q=java+software+engineer&l=United+States"
        },
    ]
    
    return direct_searches

# ─────────────────────────────────────────
#  GOOGLE SEARCH URLS (ready to paste)
# ─────────────────────────────────────────
def generate_google_search_urls(days=1):
    """
    Generate Google site: search URLs for each closed ATS
    Paste these in browser → filter to Past 24 Hours
    """
    searches = []
    date_filter = "qdr:d" if days <= 1 else f"qdr:d{days}"

    ats_sites = [
        ("All Taleo",         "taleo.net",                "java software engineer united states"),
        ("All iCIMS",         "icims.com",                "java software engineer"),
        ("Cognizant",         "cognizant.taleo.net",      "java software engineer"),
        ("Oracle Taleo",      "oracle.taleo.net",         "java developer"),
        ("Ford",              "ford.taleo.net",           "java software engineer"),
        ("UnitedHealth",      "careers.unitedhealthgroup.icims.com", "java"),
        ("FedEx",             "careers.fedex.icims.com",  "java software engineer"),
        ("Amazon",            "amazon.jobs",              "java software engineer"),
        ("Google",            "careers.google.com",       "java software engineer"),
        ("Meta",              "metacareers.com",          "software engineer java"),
        ("Microsoft",         "careers.microsoft.com",    "java software engineer"),
        ("IBM",               "ibm.com/careers",          "java developer"),
        ("Netflix",           "jobs.netflix.com",         "java software engineer"),
        ("Wipro US",          "careers.wipro.com",        "java developer united states"),
        ("HCL",               "hcltech.com/careers",      "java developer united states"),
        ("LTIMindtree",       "ltimindtree.com/careers",  "java united states"),
    ]

    for company, site, query in ats_sites:
        encoded = quote(f'site:{site} {query}')
        url = f"https://www.google.com/search?q={encoded}&tbs={date_filter}"
        searches.append({"company": company, "site": site, "google_url": url})

    return searches

# ─────────────────────────────────────────
#  PRINT & SAVE
# ─────────────────────────────────────────
def main():
    print("\n" + "═"*70)
    print("  🔍  MANUAL SEARCH HELPER  —  Closed ATS Companies")
    print(f"  ⏰  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("═"*70)

    # ── Section 1: Direct career page links ──
    print("\n\n  📋  DIRECT CAREER PAGE SEARCH LINKS")
    print("  (Click these to search Java jobs directly on each company site)\n")
    print("  " + "─"*66)

    direct_links = generate_direct_search_links()
    for i, item in enumerate(direct_links, 1):
        print(f"\n  {i}. 🏢 {item['company']}  [{item['ats']}]")
        print(f"     🔗 {item['url']}")

    # ── Section 2: Google site: search URLs ──
    print("\n\n  🔎  GOOGLE SITE: SEARCH URLS")
    print("  (Paste each URL in Chrome → Click Tools → Past 24 Hours)\n")
    print("  " + "─"*66)

    google_searches = generate_google_search_urls(days=1)
    for i, item in enumerate(google_searches, 1):
        print(f"\n  {i}. 🏢 {item['company']}")
        print(f"     🔗 {item['google_url']}")

    # ── Save to JSON ──
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "direct_career_links": direct_links,
        "google_search_links": google_searches
    }
    with open("manual_search_links.json", "w") as f:
        json.dump(output, f, indent=2)

    # ── Save to plain text (easier to use) ──
    with open("manual_search_links.txt", "w", encoding="utf-8") as f:
        f.write(f"MANUAL SEARCH LINKS — Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write("="*70 + "\n\n")
        
        f.write("DIRECT CAREER PAGE LINKS (Search Java Jobs)\n")
        f.write("-"*70 + "\n\n")
        for item in direct_links:
            f.write(f"{item['company']} [{item['ats']}]\n")
            f.write(f"{item['url']}\n\n")
        
        f.write("\nGOOGLE SITE: SEARCH LINKS (Paste in Chrome, filter Past 24 Hours)\n")
        f.write("-"*70 + "\n\n")
        for item in google_searches:
            f.write(f"{item['company']}\n")
            f.write(f"{item['google_url']}\n\n")

    print(f"\n\n  💾  Saved → manual_search_links.txt  (open this for easy copy-paste)")
    print(f"  💾  Saved → manual_search_links.json")
    print("═"*70 + "\n")

if __name__ == "__main__":
    main()
