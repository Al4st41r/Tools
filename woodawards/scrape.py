"""
Scrape all Wood Awards portfolio projects and write to CSV.
Handles two page formats:
  - New (approx 2018+): h1 title, p.award, p.category, div.portfolio-custom-fields
  - Old (pre-2018): h3 title, award in description h3, fields in description p with strong/br
"""

import csv
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.woodawards.com"
YEARS = [str(y) for y in range(2003, 2026)]
ARCHIVE_TPL = BASE + "/archive/winners-{year}/"
OUTPUT = "woodawards_projects.csv"
DELAY = 0.5

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0 (compatible; research-scraper/1.0)"})


def get_soup(url: str) -> BeautifulSoup:
    resp = SESSION.get(url, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def collect_project_urls(year: str) -> list[str]:
    url = ARCHIVE_TPL.format(year=year)
    try:
        soup = get_soup(url)
    except Exception as e:
        print(f"  [skip] {url}: {e}")
        return []
    links = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/portfolio/" in href:
            if href.startswith("/"):
                href = BASE + href
            links.add(href.rstrip("/") + "/")
    return sorted(links)


def page_title_from_tag(soup: BeautifulSoup) -> str:
    """Extract project name from the HTML <title> tag, stripping site suffix."""
    title_tag = soup.find("title")
    if title_tag:
        text = title_tag.get_text()
        return text.split("|")[0].strip()
    return ""


def scrape_new_format(soup: BeautifulSoup, row: dict) -> None:
    """New-format pages: h1, p.award, p.category, div.portfolio-custom-fields."""
    h1 = soup.find("h1")
    row["title"] = h1.get_text(strip=True) if h1 else page_title_from_tag(soup)

    award_p = soup.find("p", class_="award")
    if award_p:
        spans = award_p.find_all("span")
        row["award"] = " ".join(s.get_text(strip=True) for s in spans)

    cat_p = soup.find("p", class_="category")
    if cat_p:
        span = cat_p.find("span")
        row["category"] = span.get_text(strip=True) if span else cat_p.get_text(strip=True)

    cf_div = soup.find("div", class_="portfolio-custom-fields")
    if cf_div:
        for p in cf_div.find_all("p"):
            strong = p.find("strong")
            if strong:
                label = strong.get_text(strip=True).rstrip(":")
                strong.extract()
                value = p.get_text(strip=True)
                row[label] = value


def scrape_old_format(soup: BeautifulSoup, row: dict) -> None:
    """Old-format pages: h3 title, award in description, fields in strong/br paragraph."""
    row["title"] = page_title_from_tag(soup)

    desc = soup.find("div", class_="portfolio-detail-description-text")
    if desc:
        # First h3 in the description block holds the award text
        h3 = desc.find("h3")
        if h3:
            row["award"] = h3.get_text(strip=True)

        # Fields paragraph: <strong>Label:</strong> Value <br/> …
        for p in desc.find_all("p"):
            strongs = p.find_all("strong")
            if not strongs:
                continue
            # Walk through NavigableString/Tag siblings to pair label → value
            for strong in strongs:
                label = strong.get_text(strip=True).rstrip(":")
                # Collect text until the next <strong> or <br>
                value_parts = []
                for sibling in strong.next_siblings:
                    if sibling.name == "strong":
                        break
                    if sibling.name == "br":
                        continue
                    text = str(sibling) if hasattr(sibling, "name") else sibling
                    cleaned = str(text).strip().lstrip(":").strip()
                    if cleaned:
                        value_parts.append(cleaned)
                if label:
                    row[label] = " ".join(value_parts).strip()


def body_category(soup: BeautifulSoup) -> str:
    body_cls = " ".join(soup.body.get("class", [])) if soup.body else ""
    m = re.search(r"portfolio-category-([\w-]+)", body_cls)
    return m.group(1).replace("-", " ").title() if m else ""


def scrape_project(url: str, year: str) -> dict:
    soup = get_soup(url)
    row: dict = {"year": year, "url": url, "title": "", "award": "", "category": ""}

    # Detect format: new pages have <h1>, old ones don't
    if soup.find("h1"):
        scrape_new_format(soup, row)
    else:
        scrape_old_format(soup, row)

    # Category fallback via body class (works for both formats)
    if not row.get("category"):
        row["category"] = body_category(soup)

    return row


def main():
    all_rows: list[dict] = []
    seen_urls: set[str] = set()

    for year in YEARS:
        print(f"Year {year}…")
        urls = collect_project_urls(year)
        print(f"  {len(urls)} projects found")
        time.sleep(DELAY)

        for url in urls:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                row = scrape_project(url, year)
                all_rows.append(row)
                print(f"    {row['title']!r} [{row['award']}]")
            except Exception as e:
                print(f"    [error] {url}: {e}")
            time.sleep(DELAY)

    if not all_rows:
        print("No data collected.")
        return

    fieldnames: list[str] = ["year", "title", "award", "category", "url"]
    seen_fields = set(fieldnames)
    for row in all_rows:
        for k in row:
            if k not in seen_fields:
                fieldnames.append(k)
                seen_fields.add(k)

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nDone. {len(all_rows)} projects written to {OUTPUT}")


if __name__ == "__main__":
    main()
