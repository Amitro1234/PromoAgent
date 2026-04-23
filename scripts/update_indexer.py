"""
update_indexer.py

Updates the Azure AI Search indexer "search-1775984451728-indexer" to:
  - skillsetName   -> "word-docs-skillset"
  - targetIndexName -> "word-docs"
  - outputFieldMappings: /document/chunks/*/content_vector -> content_vector
  (dataSourceName and all other settings are preserved from the live definition)

Then resets the indexer, triggers a run, and polls status every 10 s until done.

Usage:
    python update_indexer.py
"""

import os
import time
import warnings
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

AZURE_SEARCH_ENDPOINT = os.getenv("AZURE_SEARCH_ENDPOINT")
AZURE_SEARCH_KEY = os.getenv("AZURE_SEARCH_KEY")

INDEXER_NAME = "search-1775984451728-indexer"
SKILLSET_NAME = "word-docs-skillset"
TARGET_INDEX = "word-docs"

API_VERSION = "2024-09-01-preview"
POLL_INTERVAL_S = 10
MAX_WAIT_MIN = 60       # abort polling after this many minutes


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _headers() -> dict:
    return {"Content-Type": "application/json", "api-key": AZURE_SEARCH_KEY}


def _url(path: str) -> str:
    return f"{AZURE_SEARCH_ENDPOINT.rstrip('/')}{path}?api-version={API_VERSION}"


def _get(path: str) -> dict:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.get(_url(path), headers=_headers(), timeout=30)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict) -> requests.Response:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.put(_url(path), headers=_headers(), json=body, timeout=30)
    return r


def _post(path: str) -> requests.Response:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        r = requests.post(_url(path), headers=_headers(), timeout=30)
    return r


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if not AZURE_SEARCH_ENDPOINT or not AZURE_SEARCH_KEY:
        raise EnvironmentError(
            "AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_KEY must be set in .env"
        )

    # -----------------------------------------------------------------------
    # 1. Fetch the live indexer definition to preserve all existing settings
    # -----------------------------------------------------------------------
    print(f"Fetching current definition of '{INDEXER_NAME}' ...")
    indexer = _get(f"/indexers/{INDEXER_NAME}")

    print(f"  dataSourceName  : {indexer['dataSourceName']}")
    print(f"  targetIndexName : {indexer.get('targetIndexName')!r}  ->  {TARGET_INDEX!r}")
    print(f"  skillsetName    : {indexer.get('skillsetName')!r}  ->  {SKILLSET_NAME!r}")

    # -----------------------------------------------------------------------
    # 2. Apply changes — preserve everything else
    # -----------------------------------------------------------------------
    indexer["targetIndexName"] = TARGET_INDEX
    indexer["skillsetName"] = SKILLSET_NAME

    # With a skillset, Azure Search applies a stricter "oversized" threshold.
    # Setting this to False ensures /document/content is always populated in
    # the enrichment tree so the SplitSkill can read it.
    config = indexer.setdefault("parameters", {}).setdefault("configuration", {})
    config["indexStorageMetadataOnlyForOversizedDocuments"] = False

    indexer["outputFieldMappings"] = []

    # Strip read-only / system fields that must not be sent in a PUT body
    for key in ("@odata.context", "@odata.etag"):
        indexer.pop(key, None)

    # -----------------------------------------------------------------------
    # 3. PUT the updated definition
    # -----------------------------------------------------------------------
    print(f"\nUpdating indexer '{INDEXER_NAME}' ...")
    r = _put(f"/indexers/{INDEXER_NAME}", indexer)

    if r.status_code == 201:
        print(f"  Indexer created (HTTP 201).")
    elif r.status_code in (200, 204):
        # 200 = updated with body returned; 204 = updated, no body (both are success)
        print(f"  Indexer updated (HTTP {r.status_code}).")
    else:
        print(f"  ERROR {r.status_code}:\n{r.text}")
        r.raise_for_status()

    # -----------------------------------------------------------------------
    # 4. Reset (clears the high-water mark — forces reprocessing of all docs)
    # -----------------------------------------------------------------------
    print(f"\nResetting indexer ...")
    r = _post(f"/indexers/{INDEXER_NAME}/reset")
    if r.status_code == 204:
        print("  Reset OK (204).")
    else:
        print(f"  ERROR {r.status_code}: {r.text}")
        r.raise_for_status()

    # -----------------------------------------------------------------------
    # 5. Run
    # -----------------------------------------------------------------------
    print(f"\nTriggering indexer run ...")
    r = _post(f"/indexers/{INDEXER_NAME}/run")
    if r.status_code == 202:
        print("  Run accepted (202). Starting to poll ...\n")
    else:
        print(f"  ERROR {r.status_code}: {r.text}")
        r.raise_for_status()

    # -----------------------------------------------------------------------
    # 6. Poll until done
    # -----------------------------------------------------------------------
    # Terminal statuses as defined by the Azure Search indexer status API
    TERMINAL = {"success", "transientFailure", "error"}
    deadline = time.monotonic() + MAX_WAIT_MIN * 60
    last_result: dict = {}

    while time.monotonic() < deadline:
        time.sleep(POLL_INTERVAL_S)

        status_data = _get(f"/indexers/{INDEXER_NAME}/status")
        last_result = status_data.get("lastResult") or {}
        run_status = last_result.get("status", "—")
        processed = last_result.get("itemsProcessed", 0)
        failed = last_result.get("itemsFailed", 0)

        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(
            f"  [{ts} UTC]  status={run_status:<16}  "
            f"processed={processed}  failed={failed}"
        )

        if run_status in TERMINAL:
            break
    else:
        print(f"\nTimed out after {MAX_WAIT_MIN} minutes — check the portal for status.")
        return

    # -----------------------------------------------------------------------
    # 7. Final summary
    # -----------------------------------------------------------------------
    run_status = last_result.get("status", "unknown")
    processed = last_result.get("itemsProcessed", 0)
    failed = last_result.get("itemsFailed", 0)
    end_time = last_result.get("endTime", "")
    errors = last_result.get("errors") or []
    run_warnings = last_result.get("warnings") or []

    print(f"\n{'=' * 52}")
    print(f"  Final status   : {run_status}")
    print(f"  Docs processed : {processed}")
    print(f"  Docs failed    : {failed}")
    if end_time:
        print(f"  Completed at   : {end_time}")
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for e in errors[:5]:
            print(f"    -{e.get('errorMessage', e)}")
        if len(errors) > 5:
            print(f"    … and {len(errors) - 5} more")
    if run_warnings:
        print(f"\n  Warnings ({len(run_warnings)}):")
        for w in run_warnings[:5]:
            print(f"    -{w.get('message', w)}")
        if len(run_warnings) > 5:
            print(f"    … and {len(run_warnings) - 5} more")
    print("=" * 52)


if __name__ == "__main__":
    main()
