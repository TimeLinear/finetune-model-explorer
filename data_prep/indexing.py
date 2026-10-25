"""항목·모델 카드를 Vector Store 에 넣는 도메인 쪽 절차 (F2002, F2005, design/collections.md 3절).

- items: 모델당 1청크, ID item:{model_id}. 다시 실행하면 같은 ID 로 덮어써 청크 수가 늘지 않는다.
- docs(모델 카드): ensure_card_indexed(model_id) — 같은 리비전·같은 색인 규칙 버전·같은 청크 설정으로 색인돼 있으면
  아무것도 하지 않는다 (멱등). 일괄 색인 스크립트와 질문 시 즉석 수집이 같은 함수를 쓴다.
- 카드 머리말은 정해 둔 키(card.front_matter_keys)만 section="front_matter" 조각으로 넣고,
  가치가 낮은 소제목(chunk.exclude_sections)의 청크는 뺀다 (design/collections.md 3절 "카드 머리말과 섹션 처리"). 카드 파일은 그대로 둔다.
"""
import re

from common.config import setting
from data_prep.cards import (fetch_card, front_matter_text, load_manifest, read_card_body, read_front_matter,
                             save_manifest)
from data_prep.index_text import item_chunk_id, item_metadata, item_summary_text, render
from data_prep.items import items_by_id, load_items
from data_prep.summaries import latest_summaries
from vectorstore import store
from vectorstore.docs_index import SourceDoc, chunk_settings, index_document, is_done, set_status

HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")


def index_items():
    """반환: 색인한 항목 수"""
    summaries = latest_summaries()
    items = load_items()
    store.upsert(store.ITEMS,
                 ids=[item_chunk_id(it["model_id"]) for it in items],
                 texts=[render(it, item_summary_text(summaries.get(it["model_id"]))) for it in items],
                 metadatas=[item_metadata(it) for it in items])
    return len(items)


def card_doc_id(model_id):
    return f"hf_card:{model_id}"


def card_page_url(model_id, revision):
    """근거 표시용 원문 링크 (색인한 리비전의 카드 페이지)"""
    return f"https://huggingface.co/{model_id}/blob/{revision}/README.md"


def guess_lang(text):
    """카드 언어(doc_lang). 한글이 라틴 문자보다 많으면 ko, 아니면 en."""
    return "ko" if len(HANGUL.findall(text)) > len(LATIN.findall(text)) else "en"


def ensure_card_indexed(model_id, item=None):
    """반환: 'done'(이미 색인됨) | 'indexed' | 'failed'
    item 을 주면 목록 파일 대신 그 항목(카드 리비전)으로 색인한다 (데이터 갱신이 새 목록을 쓰기 전에 모델 단위로 반영할 때)."""
    item = item or items_by_id()[model_id]
    rev = item["card_revision"]
    if is_done(model_id, rev):
        return "done"
    set_status(model_id, status="indexing", card_revision=rev)
    manifest = load_manifest()
    result = fetch_card(item, manifest)
    if result != "skipped":
        save_manifest(manifest)
    body = read_card_body(model_id)
    if result in ("failed", "mismatch") or body is None:
        set_status(model_id, status="failed", card_revision=rev, error=f"card {result}")
        return "failed"
    front = front_matter_text(read_front_matter(model_id), setting("card.front_matter_keys"))
    try:
        stats = index_document(SourceDoc(
            model_id=model_id, doc_type="model_card", doc_id=card_doc_id(model_id), title=model_id,
            url=card_page_url(model_id, rev), text=body, doc_lang=guess_lang(body), revision=rev,
            extra_sections=[("front_matter", front)] if front else [],
            extra_field_names=tuple(setting("card.front_matter_keys")),
            exclude_sections=tuple(setting("chunk.exclude_sections")),
            header_label=model_id if setting("index.chunk_header") else None))
    except Exception as e:
        set_status(model_id, status="failed", card_revision=rev, error=type(e).__name__)
        raise
    set_status(model_id, status="done", card_revision=rev, chunks=stats["chunks"],
               front_matter_chunks=stats["extra"], excluded_chunks=stats["excluded"], **chunk_settings())
    return "indexed"
