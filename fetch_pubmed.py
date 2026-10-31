
import json
import os
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

PUBMED_FILE = DATA_DIR / "pubmed.json"
CLINICAL_TRIALS_FILE = DATA_DIR / "clinicaltrials.json"

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
NCBI_EMAIL = os.getenv("NCBI_EMAIL", "")

PUBMED_QUERY = '"multiple sclerosis"[Title/Abstract]'


# --------------------------------------------------
# Общие функции
# --------------------------------------------------

def fetch_json(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mir-RS research collector"}
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_text(url):
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mir-RS research collector"}
    )

    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8")


def load_existing(path):
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, list) else []

    except (json.JSONDecodeError, OSError):
        print(f"Warning: could not read {path}")
        return []


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


# --------------------------------------------------
# Классификация публикаций PubMed
# --------------------------------------------------

def classify_article(title, abstract):
    text = (title + " " + abstract).lower()

    categories = [
        (
            "Безопасность лечения",
            [
                "adverse event",
                "safety",
                "side effect",
                "toxicity",
                "infection risk",
                "safety profile"
            ]
        ),
        (
            "Ремиелинизация и восстановление",
            [
                "remyelination",
                "remyelinating",
                "neuroprotection",
                "repair",
                "regeneration",
                "axon protection"
            ]
        ),
        (
            "Лечение и препараты",
            [
                "treatment",
                "therapy",
                "therapeutic",
                "ocrelizumab",
                "ofatumumab",
                "cladribine",
                "siponimod",
                "natalizumab",
                "disease-modifying"
            ]
        ),
        (
            "Реабилитация и мобильность",
            [
                "rehabilitation",
                "physiotherapy",
                "physical therapy",
                "exercise",
                "walking",
                "mobility",
                "balance",
                "wheelchair"
            ]
        ),
        (
            "Диагностика и биомаркеры",
            [
                "biomarker",
                "diagnosis",
                "diagnostic",
                "mri",
                "magnetic resonance",
                "neurofilament",
                "imaging"
            ]
        ),
        (
            "Симптомы и прогрессирование",
            [
                "fatigue",
                "spasticity",
                "pain",
                "cognitive",
                "disability",
                "progression",
                "bladder",
                "depression"
            ]
        ),
        (
            "Причины и механизмы РС",
            [
                "pathogenesis",
                "mechanism",
                "immune system",
                "inflammation",
                "genetic",
                "environmental risk",
                "etiology"
            ]
        )
    ]

    for category, keywords in categories:
        if any(keyword in text for keyword in keywords):
            return category

    return "Другие исследования"


# --------------------------------------------------
# PubMed
# --------------------------------------------------

def collect_pubmed():
    print("Collecting PubMed publications...")

    params = {
        "db": "pubmed",
        "term": PUBMED_QUERY,
        "reldate": "30",
        "datetype": "edat",
        "retmax": "100",
        "retmode": "json"
    }

    if NCBI_EMAIL:
        params["email"] = NCBI_EMAIL

    search_url = (
        NCBI_BASE
        + "esearch.fcgi?"
        + urllib.parse.urlencode(params)
    )

    search_data = fetch_json(search_url)

    ids = search_data.get(
        "esearchresult", {}
    ).get("idlist", [])

    print(f"Found {len(ids)} recent PubMed records.")

    if not ids:
        return

    summary_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "json"
    }

    if NCBI_EMAIL:
        summary_params["email"] = NCBI_EMAIL

    summary_url = (
        NCBI_BASE
        + "esummary.fcgi?"
        + urllib.parse.urlencode(summary_params)
    )

    summary_data = fetch_json(summary_url)
    result = summary_data.get("result", {})

    abstracts = {}

    fetch_params = {
        "db": "pubmed",
        "id": ",".join(ids),
        "retmode": "xml"
    }

    if NCBI_EMAIL:
        fetch_params["email"] = NCBI_EMAIL

    fetch_url = (
        NCBI_BASE
        + "efetch.fcgi?"
        + urllib.parse.urlencode(fetch_params)
    )

    xml_text = fetch_text(fetch_url)
    root = ET.fromstring(xml_text)

    for article in root.findall(".//PubmedArticle"):
        pmid_element = article.find(
            ".//PMID"
        )

        if pmid_element is None:
            continue

        pmid = pmid_element.text or ""

        abstract_parts = []

        for abstract_text in article.findall(
            ".//Abstract/AbstractText"
        ):
            if abstract_text.text:
                abstract_parts.append(
                    abstract_text.text.strip()
                )

        abstracts[pmid] = " ".join(abstract_parts)

    existing = load_existing(PUBMED_FILE)

    records = {
        str(item.get("pmid", "")): item
        for item in existing
        if item.get("pmid")
    }

    for pmid in ids:
        item = result.get(pmid)

        if not item:
            continue

        title = item.get("title", "").strip()
        abstract = abstracts.get(pmid, "")

        authors = [
            author.get("name", "")
            for author in item.get("authors", [])
            if author.get("name")
        ]

        record = {
            "pmid": pmid,
            "title": title,
            "date": item.get("pubdate", ""),
            "journal": item.get("fulljournalname", ""),
            "authors": authors,
            "abstract": abstract,
            "category": classify_article(
                title,
                abstract
            ),
            "url": (
                "https://pubmed.ncbi.nlm.nih.gov/"
                + pmid
                + "/"
            )
        }

        records[pmid] = record

    all_records = list(records.values())

    all_records.sort(
        key=lambda x: x.get("date", ""),
        reverse=True
    )

    save_json(PUBMED_FILE, all_records)

    print(
        f"PubMed archive now contains "
        f"{len(all_records)} records."
    )


# --------------------------------------------------
# ClinicalTrials.gov
# --------------------------------------------------

def collect_clinical_trials():
    print("Collecting ClinicalTrials.gov studies...")

    base_url = (
        "https://clinicaltrials.gov/api/v2/studies"
    )

    existing = load_existing(CLINICAL_TRIALS_FILE)

    records = {
        item.get("nct_id"): item
        for item in existing
        if item.get("nct_id")
    }

    page_token = None
    pages = 0
    max_pages = 20

    while pages < max_pages:
        params = {
            "query.cond": "Multiple Sclerosis",
            "pageSize": "100",
            "format": "json"
        }

        if page_token:
            params["pageToken"] = page_token

        url = (
            base_url
            + "?"
            + urllib.parse.urlencode(params)
        )

        data = fetch_json(url)

        studies = data.get("studies", [])

        print(
            f"ClinicalTrials page {pages + 1}: "
            f"{len(studies)} studies."
        )

        for study in studies:
            protocol = study.get(
                "protocolSection", {}
            )

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

            nct_id = identification.get(
                "nctId", ""
            )

            if not nct_id:
                continue

            # Правильное получение даты последнего обновления.
            # Проверено по JSON ClinicalTrials.gov API v2.

            last_update = (
                status.get(
                    "lastUpdatePostDateStruct", {}
                ).get("date", "")
                or status.get(
                    "lastUpdatePostDate", ""
                )
                or status.get(
                    "lastUpdateSubmitDate", ""
                )
                or ""
            )

            title = (
                identification.get("briefTitle", "")
            )

            overall_status = status.get(
                "overallStatus", ""
            )

            phases = design.get("phases", [])

            study_type = design.get(
                "studyType", ""
            )

            start_date = status.get(
                "startDateStruct", {}
            ).get("date", "")

            interventions = []

            for intervention in interventions_module.get(
                "interventions", []
            ):
                name = intervention.get("name", "")

                if name:
                    interventions.append(name)

            summary = description.get(
                "briefSummary", ""
            )

            record = {
                "nct_id": nct_id,
                "title": title,
                "status": overall_status,
                "phase": phases,
                "study_type": study_type,
                "start_date": start_date,
                "last_update": last_update,
                "interventions": interventions,
                "summary": summary,
                "url": (
                    "https://clinicaltrials.gov/study/"
                    + nct_id
                )
            }

            records[nct_id] = record

        pages += 1

        page_token = data.get("nextPageToken")

        if not page_token:
            break

        time.sleep(0.3)

    all_records = list(records.values())

    all_records.sort(
        key=lambda x: x.get("last_update", ""),
        reverse=True
    )

    save_json(
        CLINICAL_TRIALS_FILE,
        all_records
    )

    print(
        f"ClinicalTrials archive now contains "
        f"{len(all_records)} records."
    )


# --------------------------------------------------
# Запуск
# --------------------------------------------------

if __name__ == "__main__":
    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    collect_pubmed()
    collect_clinical_trials()

    print("Research data collection completed.")
