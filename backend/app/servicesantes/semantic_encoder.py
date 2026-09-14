from functools import lru_cache
from typing import List

import numpy as np
from sentence_transformers import SentenceTransformer


MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


@lru_cache(maxsize=1)
def get_semantic_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def build_semantic_embedding(text: str) -> List[float]:
    model = get_semantic_model()

    clean_text = " ".join(text.split())

    if not clean_text:
        clean_text = "Documento vacío o sin texto reconocible."

    embedding = model.encode(
        clean_text,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return embedding.astype(float).tolist()


def cosine_similarity_dense(vector_a: List[float], vector_b: List[float]) -> float:
    if not vector_a or not vector_b:
        return 0.0

    a = np.array(vector_a, dtype=float)
    b = np.array(vector_b, dtype=float)

    denominator = np.linalg.norm(a) * np.linalg.norm(b)

    if denominator == 0:
        return 0.0

    return float(np.dot(a, b) / denominator)