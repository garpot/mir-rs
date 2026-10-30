import json
import os
import re
import xml.etree.ElementTree as ET
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DATA_FILE = Path("data/pubmed.json")

# Темы и ключевые слова для предварительной классификации
CATEGORIES = {
    "Лечение и препараты": [
        "treatment", "therapy", "therapeutic", "drug",
        "ocrelizumab", "ofatumumab", "rituximab",
        "dimethyl fumarate", "disease-modifying"
    ],
    "Симптомы и прогрессирование": [
        "progression", "disability", "fatigue", "spasticity",
        "pain", "cognitive", "symptom", "relapse"
    ],
    "Ремиелинизация и восстановление": [
        "remyelination", "myelin repair", "neuroprotection",
        "axon", "neuroregeneration"
    ],
    "Диагностика и биомаркеры": [
        "diagnosis", "diagnostic", "biomarker", "neurofilament",
        "mcdonald criteria", "magnetic resonance", "mri"
    ],
    "Реабилитация и мобильность": [
        "rehabilitation", "exercise", "physical activity",
        "mobility", "balance", "stretching", "physiotherapy",
        "wheelchair"
    ],
    "Причины и механизмы РС": [
        "epstein-barr", "ebv", "genetic", "immune",
        "immunology", "inflammation", "microbiome",
        "pathogenesis", "risk factor"
    ],
    "Безопасность лечения": [
        "safety", "adverse event", "side effect",
        "infection", "pharmacovigilance"
    ],
}


def classify_article(title, abstract):
    text = f"{title} {abstract}".lower()
    categories = []

    for category, keywords in CATEGORIES.items():
        if any(keyword in text for keyword in keywords):
            categories.append(category)

    return categories or ["Другие исследования"]


def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mir-RS research archive"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mir-RS research archive"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


# Ищем публикации о рассеянном склерозе за последние 30 дней
params = {
    "db": "pubmed",
    "term": '"multiple sclerosis"[Title/Abstract]',
    "datetype": "pdat",
    "reldate": "30",
    "sort": "date",
    "retmax": "100",
    "retmode": "json"
}

email = os.environ.get("NCBI_EMAIL")
if email:
    params["email"] = email

url = BASE + "esearch.fcgi?" + urllib.parse.urlencode(params)
search_data = fetch_json(url)
ids = search_data["esearchresult"]["idlist"]

# Загружаем существующий архив
DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

if DATA_FILE.exists():
    old_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
else:
    old_data = []

records = {str(item["pmid"]): item for item in old_data}

if ids:
    # Получаем библиографические данные
    summary_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "json"
    }
    summary_url = BASE + "esummary.fcgi?" + urllib.parse.urlencode(
        summary_params
    )
    summary_data = fetch_json(summary_url)

    # Получаем аннотации
    fetch_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "rettype": "abstract",
        "retmode": "xml"
    }
    fetch_url = BASE + "efetch.fcgi?" + urllib.parse.urlencode(
        fetch_params
    )
    abstracts_xml = fetch_text(fetch_url)

    root = ET.fromstring(abstracts_xml)
    abstracts = {}

    for article in root.findall(".//PubmedArticle"):
        pmid_element = article.find(".//PMID")
        if pmid_element is None:
            continue

        pmid = pmid_element.text
        parts = []

        for part in article.findall(".//Abstract/AbstractText"):
            text = "".join(part.itertext()).strip()
            if text:
                label = part.attrib.get("Label", "")
                parts.append(f"{label}: {text}" if label else text)

        abstracts[pmid] = " ".join(parts)

    # Добавляем новые записи и обновляем найденные
    for pmid in ids:
        item = summary_data["result"].get(pmid)
        if not item:
            continue

        abstract = abstracts.get(pmid, "")
        title = item.get("title", "")

        authors = [
            author.get("name", "")
            for author in item.get("authors", [])[:5]
        ]

        previous = records.get(pmid, {})

        records[pmid] = {
            "pmid": pmid,
            "title": title,
            "date": item.get("pubdate", ""),
            "journal": item.get("fulljournalname", ""),
            "authors": authors,
            "abstract": abstract or previous.get("abstract", ""),
            "categories": classify_article(
                title,
                abstract or previous.get("abstract", "")
            ),
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        }

# Классифицируем и старые записи, не удаляя их
for record in records.values():
    record.setdefault("abstract", "")
    record["categories"] = classify_article(
        record.get("title", ""),
        record.get("abstract", "")
    )

# Сортируем архив по дате
result = list(records.values())
result.sort(key=lambda x: x.get("date", ""), reverse=True)

# Сохраняем весь архив
DATA_FILE.write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(f"Найдено публикаций за последние 30 дней: {len(ids)}")
print(f"Всего публикаций в архиве: {len(result)}")
print("Тематическая классификация завершена.")
