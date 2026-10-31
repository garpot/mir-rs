
import json
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
DATA_FILE = Path("data/pubmed.json")
TRIALS_FILE = Path("data/clinicaltrials.json")

CATEGORIES = {
    "Лечение и препараты": [
        "randomized trial", "clinical trial",
        "efficacy", "therapeutic effect",
        "ocrelizumab", "ofatumumab", "rituximab",
        "dimethyl fumarate", "disease-modifying therapy"
    ],
    "Симптомы и прогрессирование": [
        "progression", "disability", "fatigue",
        "spasticity", "pain", "cognitive impairment",
        "symptom", "relapse"
    ],
    "Ремиелинизация и восстановление": [
        "remyelination", "myelin repair",
        "neuroprotection", "axon regeneration",
        "neuroregeneration"
    ],
    "Диагностика и биомаркеры": [
        "diagnosis", "diagnostic", "biomarker",
        "neurofilament", "mcdonald criteria",
        "magnetic resonance imaging", "mri"
    ],
    "Реабилитация и мобильность": [
        "rehabilitation", "physical activity",
        "mobility", "balance training",
        "physiotherapy", "wheelchair"
    ],
    "Причины и механизмы РС": [
        "epstein-barr", "ebv", "genetic",
        "immunology", "inflammation",
        "microbiome", "pathogenesis", "risk factor"
    ],
    "Безопасность лечения": [
        "adverse event", "side effect",
        "infection risk", "safety profile",
        "pharmacovigilance"
    ],
}


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


def classify_article(title, abstract):
    text = f"{title} {abstract}".lower()
    categories = []

    for category, keywords in CATEGORIES.items():
        if any(keyword in text for keyword in keywords):
            categories.append(category)

    return categories or ["Другие исследования"]


# --------------------------------------------------
# 1. PUBMED: сбор научных публикаций
# --------------------------------------------------

def collect_pubmed():
    print("Начинаем сбор PubMed...")

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

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    if DATA_FILE.exists():
        old_data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    else:
        old_data = []

    records = {
        str(item["pmid"]): item
        for item in old_data
    }

    if ids:
        summary_params = {
            "db": "pubmed",
            "id": ",".join(ids),
            "retmode": "json"
        }

        summary_url = BASE + "esummary.fcgi?" + urllib.parse.urlencode(
            summary_params
        )
        summary_data = fetch_json(summary_url)

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
                    parts.append(
                        f"{label}: {text}" if label else text
                    )

            abstracts[pmid] = " ".join(parts)

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

    for record in records.values():
        record.setdefault("abstract", "")
        record["categories"] = classify_article(
            record.get("title", ""),
            record.get("abstract", "")
        )

    result = list(records.values())
    result.sort(
        key=lambda x: x.get("date", ""),
        reverse=True
    )

    DATA_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"PubMed: новых публикаций за 30 дней — {len(ids)}")
    print(f"PubMed: всего записей в архиве — {len(result)}")


# --------------------------------------------------
# 2. CLINICALTRIALS.GOV: сбор клинических испытаний
# --------------------------------------------------

def collect_clinical_trials():
    print("Начинаем сбор ClinicalTrials.gov...")

    base_url = "https://clinicaltrials.gov/api/v2/studies"

    records = {}

    if TRIALS_FILE.exists():
        old_data = json.loads(
            TRIALS_FILE.read_text(encoding="utf-8")
        )
    else:
        old_data = []

    for item in old_data:
        records[item["nct_id"]] = item

    page_token = None
    pages = 0

    while pages < 20:
        params = {
            "query.cond": "Multiple Sclerosis",
            "pageSize": "100",
            "format": "json"
        }

        if page_token:
            params["pageToken"] = page_token

        url = base_url + "?" + urllib.parse.urlencode(params)
        data = fetch_json(url)

        studies = data.get("studies", [])

        for study in studies:
            protocol = study.get("protocolSection", {})

            identification = protocol.get(
                "identificationModule", {}
            )

            status = protocol.get(
                "statusModule", {}
            )

            design = protocol.get(
                "designModule", {}
            )

            description = protocol.get(
                "descriptionModule", {}
            )

            interventions_module = protocol.get(
                "armsInterventionsModule", {}
            )

            conditions_module = protocol.get(
                "conditionsModule", {}
            )

            nct_id = identification.get("nctId")

            if not nct_id:
                continue

            title = identification.get(
                "briefTitle", ""
            )

            interventions = []

            for intervention in interventions_module.get(
                "interventions", []
            ):
                name = intervention.get("name", "")

                if name:
                    interventions.append(name)

            phases = design.get("phases", [])

            summary = description.get(
                "briefSummary", ""
            )

            conditions = conditions_module.get(
                "conditions", []
            )

            records[nct_id] = {
                "nct_id": nct_id,
                "title": title,
                "status": status.get(
                    "overallStatus", "Не указан"
                ),
                "phase": phases,
                "study_type": design.get(
                    "studyType", ""
                ),
                "start_date": status.get(
                    "startDateStruct", {}
                ).get("date", ""),
                "last_update": status.get(
                    "studyFirstPostDateStruct", {}
                ).get("date", ""),
                "interventions": interventions,
                "conditions": conditions,
                "summary": summary,
                "url": (
                    "https://clinicaltrials.gov/study/"
                    + nct_id
                )
            }

        pages += 1
        page_token = data.get("nextPageToken")

        if not page_token:
            break

        time.sleep(0.3)

    result = list(records.values())

    result.sort(
        key=lambda x: x.get("last_update", ""),
        reverse=True
    )

    TRIALS_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    TRIALS_FILE.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"ClinicalTrials.gov: обработано страниц — {pages}")
    print(f"ClinicalTrials.gov: всего исследований — {len(result)}")


# --------------------------------------------------
# 3. ЗАПУСК ОБОИХ СБОРЩИКОВ
# --------------------------------------------------

if __name__ == "__main__":
    collect_pubmed()
    collect_clinical_trials()

    print("Сбор данных завершён.")
