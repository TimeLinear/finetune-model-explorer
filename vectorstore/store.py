"""Chroma 컬렉션 2개 (design/collections.md 4절): items(모델당 1청크), docs(모델 카드 + 위키 청크).

청크 ID 는 무작위가 아니라 규칙으로 만든다. 같은 ID 로 다시 넣으면 덮어쓰기(upsert)가 된다.
"""
import os
import threading
from functools import lru_cache

import chromadb
from langchain_chroma import Chroma

from common.config import CHROMA_DIR
from vectorstore.embeddings import get_embeddings

ITEMS = "items"
DOCS = "docs"
COLLECTION_METADATA = {"hnsw:space": "cosine"}
_client_lock = threading.Lock()


def chroma_path():
    """Chroma 1.5.9 는 ASCII 가 아닌 경로(예: C:\\사용자\\프로젝트\\...)에서 HNSW 색인을 다시 읽지 못한다 (9.2절).
    절대 경로가 ASCII 가 아니면 현재 폴더 기준 상대 경로(프로젝트 루트에서 실행 시 data\\chroma)를 쓴다."""
    path = CHROMA_DIR.resolve()
    if str(path).isascii():
        return str(path)
    try:
        rel = os.path.relpath(path)
    except ValueError:  # 다른 드라이브
        rel = ""
    if rel.isascii() and rel:
        return rel
    raise RuntimeError("Chroma 색인 폴더 경로에 ASCII 가 아닌 문자가 있습니다. "
                       "프로젝트 루트에서 실행하거나 CHROMA_DIR 환경 변수로 ASCII 경로를 지정하세요.")


_client = []


def client():
    """프로세스당 1개. 여러 스레드가 처음에 동시에 부르면 Chroma 내부 생성이 충돌하므로 잠금 안에서 만든다."""
    if not _client:
        with _client_lock:
            if not _client:
                CHROMA_DIR.mkdir(parents=True, exist_ok=True)
                _client.append(chromadb.PersistentClient(path=chroma_path()))
    return _client[0]


@lru_cache
def get_store(name):
    return Chroma(client=client(), collection_name=name, embedding_function=get_embeddings(),
                  collection_metadata=COLLECTION_METADATA)


def count(name):
    """임베딩 모델을 올리지 않고 청크 수만 센다 (화면 표시용)."""
    try:
        return client().get_collection(name).count()
    except Exception:  # 컬렉션이 아직 없으면 0
        return 0


def upsert(name, ids, texts, metadatas, embed_texts=None):
    """embed_texts 를 주면 저장하는 본문(texts)과 다른 문자열로 임베딩한다 (예: 조각 머리표를 붙인 입력)."""
    if not ids:
        return
    if embed_texts is None:
        get_store(name).add_texts(texts=texts, metadatas=metadatas, ids=ids)
        return
    embeddings = get_embeddings().embed_documents(embed_texts)
    client().get_or_create_collection(name, metadata=COLLECTION_METADATA).upsert(
        ids=ids, embeddings=embeddings, documents=texts, metadatas=metadatas)


def delete_where(name, where):
    client().get_or_create_collection(name, metadata=COLLECTION_METADATA).delete(where=where)


def get_by_ids(name, ids):
    got = client().get_or_create_collection(name, metadata=COLLECTION_METADATA).get(ids=ids)
    return [{"id": i, "text": t, "metadata": m} for i, t, m in zip(got["ids"], got["documents"], got["metadatas"])]


def get_where(name, where, limit=None):
    got = client().get_or_create_collection(name, metadata=COLLECTION_METADATA).get(where=where, limit=limit)
    return [{"id": i, "text": t, "metadata": m} for i, t, m in zip(got["ids"], got["documents"], got["metadatas"])]


def search(name, query, k, where=None, search_type="similarity", fetch_k=None, lambda_mult=None):
    """유사도 또는 MMR 검색 (F2006, F2014). 반환: [{id, text, metadata}]"""
    store = get_store(name)
    if search_type == "mmr":
        docs = store.max_marginal_relevance_search(query, k=k, fetch_k=fetch_k, lambda_mult=lambda_mult, filter=where)
    else:
        docs = store.similarity_search(query, k=k, filter=where)
    return [{"id": d.id, "text": d.page_content, "metadata": d.metadata} for d in docs]
