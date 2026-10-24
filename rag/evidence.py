"""근거 목록 구성과 인용 확인 (F2006~F2008).

- 항목 청크는 항상 [근거 1] (검색 없이 포함). 끝에 "최근 30일 다운로드" 한 줄을 메타데이터에서 덧붙인다 (design/collections.md 2절).
- 문서 청크는 청크 ID 로 중복을 제거한 뒤 이어서 번호를 붙인다.
- 답변에서 [근거 n] 을 찾아 실제로 인용된 근거만 돌려준다.
"""
import re

from common.config import fill, texts


def make_evidence(item_chunk, doc_chunks):
    """[{n, chunk_id, source_type, title, url, section, text, model_id, downloads, snapshot_date}]"""
    out, seen = [], set()
    if item_chunk:
        m = item_chunk["metadata"]
        out.append({"chunk_id": item_chunk["id"], "source_type": "item", "model_id": m["model_id"],
                    "title": m["model_id"], "url": m.get("card_url"), "section": None,
                    "text": item_chunk["text"], "downloads": m.get("downloads_30d_adj"),
                    "snapshot_date": m.get("snapshot_date")})
        seen.add(item_chunk["id"])
    for c in doc_chunks:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        m = c["metadata"]
        out.append({"chunk_id": c["id"], "source_type": m["doc_type"], "model_id": m["model_id"],
                    "title": m.get("title"), "url": m.get("url"), "section": m.get("section"), "text": c["text"]})
    for n, ev in enumerate(out, 1):
        ev["n"] = n
    return out


def format_block(ev):
    t = texts()["evidence_block"]
    downloads = f"{ev['downloads']:,}" if isinstance(ev.get("downloads"), int) else ev.get("downloads")
    return fill(t[ev["source_type"]], n=ev["n"], model_id=ev["model_id"], text=ev["text"], title=ev.get("title") or "",
                section=ev.get("section") or "-", downloads=downloads, snapshot_date=ev.get("snapshot_date") or "")


def format_blocks(evidence):
    return "\n\n".join(format_block(ev) for ev in evidence)


def citation_pattern():
    label = re.escape(texts()["citation_label"])
    return re.compile(rf"\[{label}\s*(\d+)\]")


def cited_numbers(answer):
    return sorted({int(n) for n in citation_pattern().findall(answer or "")})


def strip_citations(answer):
    return re.sub(r"[ \t]*" + citation_pattern().pattern, "", answer or "")


def cited_evidence(answer, evidence):
    """답변에 실제로 인용된 근거만 (번호 순). 없는 번호는 무시한다."""
    nums = set(cited_numbers(answer))
    return [ev for ev in evidence if ev["n"] in nums]


def display_fields(ev):
    """화면·세션 저장용 (본문 제외)"""
    return {k: ev.get(k) for k in ("n", "source_type", "title", "url", "section")}
