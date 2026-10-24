"""로컬 임베딩 (design/models.md: 한국어 질문 ↔ 영어 문서 교차 검색, API 크레딧과 무관하게 운영). 모델 이름은 설정 embedding.model."""
from functools import lru_cache

from langchain_core.embeddings import Embeddings

from common import perf
from common.config import setting

BATCH_SIZE = 16


class LocalEmbeddings(Embeddings):
    def __init__(self, model_name):
        with perf.step("embedding_model_load"):
            from sentence_transformers import SentenceTransformer  # 무거운 import 는 실제로 쓸 때만
            self.model = SentenceTransformer(model_name, device="cpu")

    def embed_documents(self, texts):
        return self.model.encode(list(texts), batch_size=BATCH_SIZE, normalize_embeddings=True,
                                 show_progress_bar=False).tolist()

    def embed_query(self, text):
        return self.embed_documents([text])[0]


@lru_cache
def get_embeddings():
    return LocalEmbeddings(setting("embedding.model"))
