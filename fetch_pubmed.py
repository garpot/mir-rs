
import json
import xml.etree.ElementTree as ET
import os
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DATA_FILE = Path("data/pubmed.json")

# Ищем новые публикации о рассеянном склерозе
params = {
    "db": "pubmed",
    "term": (
        '"multiple sclerosis"[Title/Abstract] '
        'AND ('
        'treatment[Title/Abstract] OR therapy[Title/Abstract] '
        'OR progression[Title/Abstract] OR diagnosis[Title/Abstract] '
        'OR rehabilitation[Title/Abstract] OR symptoms[Title/Abstract] '
        'OR fatigue[Title/Abstract] OR disability[Title/Abstract] '
        'OR remyelination[Title/Abstract] OR clinical trial[Title/Abstract] '
        'OR "disease modifying"[Title/Abstract]'
        ')'
    ),
    "datetype": "pdat",
    "reldate": "30",
    "sort": "date",
    "retmax": "30",
    "retmode": "json"
}

email = os.environ.get("NCBI_EMAIL")
if email:
    params["email"] = email

url = BASE + "esearch.fcgi?" + urllib.parse.urlencode(params)

with urllib.request.urlopen(url, timeout=30) as response:
    search_data = json.loads(response.read())

ids = search_data["esearchresult"]["idlist"]

if not ids:
    print("Новых публикаций не найдено.")
    raise SystemExit(0)

summary_params = {
    "db": "pubmed",
    "id": ",".join(ids),
    "retmode": "json"
}

url = BASE + "esummary.fcgi?" + urllib.parse.urlencode(summary_params)

with urllib.request.urlopen(url, timeout=30) as response:
    summary_data = json.loads(response.read())

fetch_params = {
    "db": "pubmed",
    "id": ",".join(ids),
    "rettype": "abstract",
    "retmode": "xml"
}

url = BASE + "efetch.fcgi?" + urllib.parse.urlencode(fetch_params)

with urllib.request.urlopen(url, timeout=30) as response:
    abstracts_xml = response.read().decode("utf-8")
    
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

if DATA_FILE.exists():
    old_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
else:
    old_data = []

records = {item["pmid"]: item for item in old_data}

root = ET.fromstring(abstracts_xml)

abstracts = {}

for article in root.findall(".//PubmedArticle"):
    pmid_element = article.find(".//PMID")

    if pmid_element is None:
        continue

    pmid = pmid_element.text

    abstract_parts = []

    for part in article.findall(".//Abstract/AbstractText"):
        text = "".join(part.itertext()).strip()

        if text:
            label = part.attrib.get("Label", "")
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)

    abstracts[pmid] = " ".join(abstract_parts)
    
for pmid in ids:
    item = summary_data["result"].get(pmid)

    if not item:
        continue

    authors = [
        author.get("name", "")
        for author in item.get("authors", [])[:5]
    ]

records[pmid] = {
    "pmid": pmid,
    "title": item.get("title", ""),
    "date": item.get("pubdate", ""),
    "journal": item.get("fulljournalname", ""),
    "authors": authors,
    "abstract": abstracts.get(pmid, ""),
    "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
}

result = list(records.values())
result.sort(key=lambda x: x["date"], reverse=True)
result = result[:100]

DATA_FILE.write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"Сохранено публикаций: {len(result)}")
