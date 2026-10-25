"""D-04 기준 조회: 공식 조직 계정의 1~24B 언어 모델 목록 (로직은 data_prep/catalog_fetch.py, 설정은 config/catalog.json).

사용: python scripts/collect.py data/raw_models.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_prep.catalog_fetch import HFClient, fetch_catalog  # noqa: E402

OUT = sys.argv[1]
client = HFClient()
result = fetch_catalog(client)
missing = result["missing_orgs"] + list(result["failed_orgs"])
with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"rows": result["rows"], "missing_orgs": missing}, f, ensure_ascii=False, indent=1)
print(len(result["rows"]), "models; missing orgs:", missing, "| HF 요청", client.requests)
