"""
Local Embedding Service using sentence-transformers (BAAI/bge-base-en-v1.5)
No API key required — runs fully offline.
"""
import re
import logging
import asyncio
from functools import partial
from typing import List, Optional

from sentence_transformers import SentenceTransformer
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Best free local model: top-ranked on MTEB, 768-dim, fast
DEFAULT_MODEL = "BAAI/bge-base-en-v1.5"


class EmbeddingService:
    """Service for generating embeddings using a local sentence-transformers model"""

    def __init__(self):
        """Load the local sentence-transformers model"""
        model_name = getattr(settings, "local_embedding_model", DEFAULT_MODEL)
        try:
            self.model = SentenceTransformer(model_name)
            self._dim = self.model.get_sentence_embedding_dimension()
            logger.info(
                f"✅ Local embedding service initialized — model: {model_name}, dim: {self._dim}"
            )
        except Exception as e:
            logger.error(f"❌ Failed to load local embedding model '{model_name}': {e}")
            raise

    # ------------------------------------------------------------------
    # Public async API (same interface as the previous Google service)
    # ------------------------------------------------------------------

    async def generate_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for a single document text."""
        cleaned = self._clean_text(text)
        if not cleaned:
            logger.warning("Empty text provided for embedding")
            return None
        try:
            # BGE models benefit from a query/document prefix
            prefixed = f"Represent this sentence: {cleaned}"
            vec = await self._encode_async(prefixed)
            logger.debug(f"Generated embedding for text of length {len(cleaned)}")
            return vec
        except Exception as e:
            logger.error(f"Error generating embedding: {e}")
            return None

    async def generate_embeddings_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """Generate embeddings for multiple texts efficiently."""
        if not texts:
            return []
        cleaned_texts = [self._clean_text(t) for t in texts]
        prefixed = [
            f"Represent this sentence: {t}" if t else None
            for t in cleaned_texts
        ]
        results: List[Optional[List[float]]] = [None] * len(texts)
        # Filter out empty entries and encode in one batch
        valid_indices = [i for i, p in enumerate(prefixed) if p]
        valid_texts = [prefixed[i] for i in valid_indices]
        if valid_texts:
            try:
                loop = asyncio.get_event_loop()
                vecs = await loop.run_in_executor(
                    None,
                    partial(self.model.encode, valid_texts, normalize_embeddings=True)
                )
                for idx, vec in zip(valid_indices, vecs):
                    results[idx] = vec.tolist()
            except Exception as e:
                logger.error(f"Error generating batch embeddings: {e}")
        return results

    async def  generate_query_embedding(self, query: str) -> Optional[List[float]]:
        """Generate embedding for a search query."""
        cleaned = self._clean_text(query)
        if not cleaned:
            logger.warning("Empty query provided for embedding")
            return None
        try:
            # BGE recommends a specific query prefix
            prefixed = f"Represent this question for searching relevant passages: {cleaned}"
            vec = await self._encode_async(prefixed)
            logger.debug(f"Generated query embedding for: {cleaned[:50]}...")
            return vec
        except Exception as e:
            logger.error(f"Error generating query embedding: {e}")
            return None

    async def get_embedding_dimension(self) -> int:
        """Return the embedding dimension of the loaded model."""
        return self._dim

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _encode_async(self, text: str) -> List[float]:
        """Run model.encode in a thread pool so the event loop stays free."""
        loop = asyncio.get_event_loop()
        vec = await loop.run_in_executor(
            None,
            partial(self.model.encode, text, normalize_embeddings=True)
        )
        return vec.tolist()

    def _clean_text(self, text: str) -> str:
        """Basic cleaning: strip, collapse whitespace, truncate."""
        if not text:
            return ""
        cleaned = re.sub(r"\s+", " ", text.strip())
        max_length = 8192  # safe limit for most transformer models
        if len(cleaned) > max_length:
            cleaned = cleaned[:max_length]
            logger.warning(f"Text truncated to {max_length} characters")
        return cleaned


# Global singleton
embedding_service = EmbeddingService()


def get_embedding_service() -> EmbeddingService:
    """Return the global embedding service instance."""
    return embedding_service

