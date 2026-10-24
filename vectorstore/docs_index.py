"""docs 컬렉션 색인 (F2005, design/collections.md 3·5·6절).

- 청크 ID: {model_id}:{doc_id}:{chunk_index}. 여러 모델이 같은 문서를 수집해도 서로 덮어쓰지 않는다.
- 재색인 시 해당 model_id + doc_id 의 기존 청크를 먼저 지운다 (청크 수가 줄어든 경우 대비).
- 모델별 카드 색인 상태(pending / indexing / done / failed)를 색인 폴더 안 JSON 에 기록한다.
  건너뛰기 기준은 model_id + card_revision + index_version (+ 청크 설정). 색인 규칙이 바뀌면 index.version 을 올린다.
- 문서 앞에 붙일 별도 조각(extra_sections, 예: 카드 머리말)은 소제목 없이 일반 청킹 규칙으로 나눠 먼저 넣는다.
"""
import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from common import perf
from common.config import CHROMA_DIR, setting
from vectorstore import store
from vectorstore.chunking import split_markdown, split_plain

STATUS_PATH = CHROMA_DIR / "index_status.json"
_status_lock = threading.Lock()


@dataclass
class SourceDoc:
    model_id: str
    doc_type: str  # model_card / wiki
    doc_id: str
    title: str
    url: str
    text: str  # 마크다운 (소제목으로 section 을 나눈다)
    doc_lang: str
    revision: str
    extra: dict = field(default_factory=dict)  # 예: 위키 문서의 search_query
    extra_sections: list = field(default_factory=list)  # [(section, 텍스트)] 본문 앞에 넣을 조각
    extra_field_names: tuple = ()  # extra_sections 텍스트의 "이름: 값" 필드 이름 (조각 경로 계산용)
    exclude_sections: tuple = ()  # 색인에서 뺄 소제목 문구
    header_label: str | None = None  # 주면 임베딩 입력 앞에 "[header_label | 소제목 경로]" 를 붙인다 (저장 본문은 그대로)


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def chunk_id(model_id, doc_id, index):
    return f"{model_id}:{doc_id}:{index}"


def index_document(doc):
    """문서 하나를 청킹해 색인한다. 반환: {"chunks": 색인한 청크 수, "extra": 별도 조각 청크 수, "excluded": 제외한 청크 수}"""
    with perf.step("chunk_embed_index", doc_type=doc.doc_type):
        return _index_document(doc)


def _index_document(doc):
    store.delete_where(store.DOCS, {"$and": [{"model_id": doc.model_id}, {"doc_id": doc.doc_id}]})
    extra = [c for section, text in doc.extra_sections for c in split_plain(text, section, doc.extra_field_names)]
    body, excluded = split_markdown(doc.text, doc.exclude_sections)
    chunks = extra + body
    collected_at = now_iso()
    ids, texts, metas, embed_texts = [], [], [], []
    for i, (text, section, path) in enumerate(chunks):
        meta = {"model_id": doc.model_id, "doc_type": doc.doc_type, "doc_id": doc.doc_id, "title": doc.title,
                "url": doc.url, "section": section, "doc_lang": doc.doc_lang, "revision": doc.revision,
                "chunk_index": i, "collected_at": collected_at, **doc.extra}
        if doc.header_label:
            meta["section_path"] = path
            head = f"[{doc.header_label} | {path}]" if path else f"[{doc.header_label}]"
            embed_texts.append(f"{head}\n{text}")
        ids.append(chunk_id(doc.model_id, doc.doc_id, i))
        texts.append(text)
        metas.append({k: v for k, v in meta.items() if v not in (None, "")})
    store.upsert(store.DOCS, ids, texts, metas, embed_texts=embed_texts if doc.header_label else None)
    return {"chunks": len(ids), "extra": len(extra), "excluded": excluded}


def chunk_settings():
    return {"index_version": setting("index.version"), "chunk_splitter": setting("chunk.splitter"),
            "chunk_size": setting("chunk.size"), "chunk_overlap": setting("chunk.overlap")}


def load_status():
    if STATUS_PATH.exists():
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    return {}


def set_status(model_id, **rec):
    with _status_lock:
        status = load_status()
        status[model_id] = {**rec, "updated_at": now_iso()}
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")


def is_done(model_id, revision):
    """같은 리비전·같은 색인 규칙 버전·같은 청크 설정으로 색인을 마쳤는가"""
    rec = load_status().get(model_id) or {}
    return (rec.get("status") == "done" and rec.get("card_revision") == revision
            and all(rec.get(k) == v for k, v in chunk_settings().items()))
