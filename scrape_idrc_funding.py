import os
import pandas as pd
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --- Setup headless Chrome ---
options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")

driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)

# --- Visit IDRC funding page ---
url = "https://idrc-crdi.ca/en/funding"
driver.get(url)

# --- Wait for funding items to load ---
WebDriverWait(driver, 10).until(
    EC.presence_of_element_located((By.CLASS_NAME, "views-row"))
)

# --- Get page source and close browser ---
soup = BeautifulSoup(driver.page_source, 'html.parser')
driver.quit()

# --- Scrape funding entries ---
funding_blocks = soup.select("div.views-row")
funding_data = []

for block in funding_blocks:
    title_tag = block.select_one("div.views-field-title span.field-content a")
    title = title_tag.get_text(strip=True) if title_tag else 'N/A'
    url = "https://idrc-crdi.ca" + title_tag['href'] if title_tag and title_tag.has_attr('href') else 'N/A'

    deadline_tag = block.select_one("div.views-field-field-award-deadline time")
    deadline = deadline_tag.get_text(strip=True) if deadline_tag else 'N/A'

    # Parse deadline and determine opportunity status
    try:
        deadline_date = datetime.strptime(deadline, "%B %d, %Y")
        status = "Open" if deadline_date >= datetime.today() else "Closed"
    except Exception:
        status = "Unknown"

    funding_data.append({
        "Title": title,
        "URL": url,
        "Deadline": deadline,
        "Opportunity Status": status
    })

# --- Save new file (no duplicate logic for simplicity here) ---
df = pd.DataFrame(funding_data)
df.to_csv("idrc_funding_opportunities_detailed..csv", index=False)

print("✅ Scraping done — check 'Opportunity Status' in 'idrc_funding_opportunities_detailed..csv'")
