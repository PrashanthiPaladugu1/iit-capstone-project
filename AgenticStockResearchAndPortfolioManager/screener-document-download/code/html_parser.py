"""Parse the #documents section of a Screener company page."""
from __future__ import annotations

import logging
import re
from typing import List, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from config import BASE_URL, LOGGER_NAME, MONTHS
from fs_utils import sanitize_filename
from models import Doc

log = logging.getLogger(LOGGER_NAME)


def parse_documents(html: str) -> List[Doc]:
    soup = BeautifulSoup(html, "html.parser")
    section = soup.select_one("#documents")
    if section is None:
        return []

    docs: List[Doc] = []
    seen: Set[str] = set()

    def add(kind: str, label: str, href: str) -> None:
        url = urljoin(BASE_URL, href.strip())
        if url not in seen:
            seen.add(url)
            docs.append(Doc(kind, label, url))

    # Annual reports: <li><a href=pdf>Annual Report 2026</a> ... AI Summary button</li>
    for a in section.select("div.annual-reports ul.list-links > li > a[href]"):
        text = a.get_text(" ", strip=True)
        year = re.search(r"(19|20)\d{2}", text)
        label = year.group(0) if year else sanitize_filename(text)
        add("Annual_Report", label, a["href"])

    # Concalls: each <li> = "Mon YYYY" + chip links (Transcript / PPT / REC) + AI Summary button
    for li in section.select("div.concalls ul.list-links > li"):
        date_div = li.find("div")
        date_text = date_div.get_text(" ", strip=True) if date_div else ""
        m = re.search(r"([A-Za-z]{3})[a-z]*\s+((?:19|20)\d{2})", date_text)
        if not m or m.group(1).title() not in MONTHS:
            log.debug("Skipping concall row without a parsable date: %r", date_text)
            continue
        label = f"{m.group(1).title()}_{m.group(2)}"
        for a in li.find_all("a", href=True):  # AI Summary is a <button>, so it's ignored
            chip = a.get_text(" ", strip=True).lower()
            if chip == "transcript":
                add("Transcript", label, a["href"])
            elif chip == "ppt":
                add("PPT", label, a["href"])
            # "REC" (audio recording) and anything else is skipped.
    return docs
