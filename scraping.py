import os
import json
import math
import time
import requests
import pandas as pd
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# ---------- Shared Utilities ----------
def format_date(date_str):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except:
            continue
    return "Not specified"

# ---------- NIH Fetch ----------
def fetch_nih_by_year(year, batch_size=500):
    url = "https://api.reporter.nih.gov/v2/projects/search"
    headers = {"Content-Type": "application/json"}
    offset = 0
    records = []

    while True:
        payload = {
            "criteria": {"textSearch": "machine learning", "fiscalYears": [year]},
            "includeFields": [
                "project_title", "project_num", "project_start_date", "project_end_date", "award_amount"
            ],
            "offset": offset,
            "limit": batch_size
        }

        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            results = response.json().get("results", [])
            if not results:
                break

            for item in results:
                award_amount = item.get('award_amount')
                funding_str = f"${award_amount:,.2f}" if award_amount else "Not listed"

                records.append({
                    "Title": item.get("project_title", ""),
                    "URL": f"https://reporter.nih.gov/project-details/{item.get('project_num', '')}",
                    "Deadline": format_date(item.get("project_end_date", "")),
                    "Call For": "Research Grant",
                    "Opportunity Status": "Awarded",
                    "Estimated Funding": funding_str,
                    "Source": "NIH RePORTER",
                    "Year": year
                })

            offset += batch_size
        except Exception as e:
            print(f"❌ NIH error for year {year}, offset {offset}: {e}")
            break

    print(f"✅ Fetched NIH records for year {year}: {len(records)}")
    return records

# ---------- Grants.gov Fetch ----------
def fetch_grants_page(start_record, page_size, seen_titles):
    url = "https://api.grants.gov/v1/api/search2"
    headers = {"Content-Type": "application/json"}
    payload = {
        "startRecord": start_record,
        "rows": page_size,
        "fundingCategories": "HL|ED|EN|ST",
        "fundingInstruments": "G",
        "oppStatuses": "posted"
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        results = data.get("data", {}).get("oppHits", [])
        records = []

        for item in results:
            title = item.get("title", "").strip()
            source = item.get("agencyName", "Grants.gov")
            opp_id = item.get("id")
            key = (title.lower(), source)

            deadline_str = format_date(item.get("closeDate", ""))
            year = deadline_str[:4] if deadline_str != "Not specified" else "Not specified"

            if key not in seen_titles:
                seen_titles.add(key)
                records.append({
                    "Title": title,
                    "URL": f"https://www.grants.gov/search-results-detail/{opp_id}",
                    "Deadline": deadline_str,
                    "Call For": item.get("docType", "Grant").capitalize(),
                    "Opportunity Status": item.get("oppStatus", "Unknown").capitalize(),
                    "Estimated Funding": "Not listed",
                    "Source": f"Grants.gov ({source})",
                    "Year": year
                })

        print(f"✅ Grants.gov page {start_record} fetched.")
        return records

    except requests.RequestException as e:
        print(f"❌ Grants.gov error at record {start_record}: {e}")
        return []

def fetch_grants_concurrent(max_workers=5, page_size=1000):
    url = "https://api.grants.gov/v1/api/search2"
    headers = {"Content-Type": "application/json"}
    init_payload = {
        "startRecord": 1,
        "rows": 1,
        "fundingCategories": "HL|ED|EN|ST",
        "fundingInstruments": "G",
        "oppStatuses": "posted"
    }

    try:
        response = requests.post(url, headers=headers, json=init_payload)
        response.raise_for_status()
        total_records = response.json().get("data", {}).get("hitCount", 0)
    except Exception as e:
        print(f"❌ Failed to fetch total record count: {e}")
        return []

    total_pages = math.ceil(total_records / page_size)
    seen_titles = set()
    all_results = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(fetch_grants_page, page * page_size + 1, page_size, seen_titles)
            for page in range(total_pages)
        ]
        for future in as_completed(futures):
            all_results.extend(future.result())

    return all_results

# ---------- IDRC Web Scraper ----------
def fetch_idrc_opportunities():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

    url = "https://idrc-crdi.ca/en/funding"
    driver.get(url)

    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.CLASS_NAME, "views-row"))
    )

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    driver.quit()

    funding_blocks = soup.select("div.views-row")
    funding_data = []

    for block in funding_blocks:
        title_tag = block.select_one("div.views-field-title span.field-content a")
        title = title_tag.get_text(strip=True) if title_tag else 'N/A'
        url = "https://idrc-crdi.ca" + title_tag['href'] if title_tag and title_tag.has_attr('href') else 'N/A'

        deadline_tag = block.select_one("div.views-field-field-award-deadline time")
        deadline = deadline_tag.get_text(strip=True) if deadline_tag else 'N/A'

        call_for_tag = block.select_one("div.views-field-field-award-call-for span.field-content")
        call_for = call_for_tag.get_text(strip=True) if call_for_tag else 'N/A'

        try:
            deadline_date = datetime.strptime(deadline, "%B %d, %Y")
            status = "Open" if deadline_date >= datetime.today() else "Closed"
            year = deadline_date.year
        except Exception:
            status = "Unknown"
            year = "Not specified"

        funding_data.append({
            "Title": title,
            "URL": url,
            "Deadline": deadline,
            "Call For": call_for,
            "Opportunity Status": status,
            "Estimated Funding": "Not listed",
            "Source": "IDRC - CRDI",
            "Year": year
        })

    return funding_data

# ---------- Run All ----------
if __name__ == "__main__":
    # NIH
    years = list(range(2015, 2025))
    nih_results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(fetch_nih_by_year, y) for y in years]
        for future in as_completed(futures):
            nih_results.extend(future.result())
    pd.DataFrame(nih_results).to_csv("nih_funding.csv", index=False)
    with open("nih_funding.json", "w") as f: json.dump(nih_results, f, indent=2)

    # Grants.gov
    grants_gov_results = fetch_grants_concurrent(max_workers=8, page_size=1000)
    pd.DataFrame(grants_gov_results).to_csv("grantsgov_funding.csv", index=False)
    with open("grantsgov_funding.json", "w") as f: json.dump(grants_gov_results, f, indent=2)

    # IDRC
    idrc_results = fetch_idrc_opportunities()
    pd.DataFrame(idrc_results).to_csv("idrc_funding.csv", index=False)
    with open("idrc_funding.json", "w") as f: json.dump(idrc_results, f, indent=2)

    # Combine all
    all_results = nih_results + grants_gov_results + idrc_results
    unique_combined = { (item['Title'].lower(), item['Source']): item for item in all_results }
    unique_list = list(unique_combined.values())

    pd.DataFrame(unique_list).to_csv("combined_funding_opportunities.csv", index=False)
    with open("combined_funding_opportunities.json", "w") as f:
        json.dump(unique_list, f, indent=2)

    print(f"\n✅ Saved {len(unique_list)} unique funding opportunities.")
