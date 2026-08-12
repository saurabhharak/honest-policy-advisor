"""Embeddings wrapper over the existing OpenAI client for MemoryStore search.

Returns plain lists of floats; no langchain-openai dependency. Used as the
`embed` callable when building PostgresStore / InMemoryStore with semantic
search. Never raises — failures return a zero vector so store ops degrade
to lexical-only instead of crashing the pipeline.
"""

from openai import OpenAI

from policydecoder.config import get_config
from policydecoder.logging import get_logger

logger = get_logger("policydecoder.embeddings")


class Embedder:
    def __init__(self, llm_client: OpenAI | None = None, model: str | None = None):
        self.llm = llm_client
        self.model = model or get_config().embeddings_model
        self._failed = False

    def __call__(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of strings into a list of vectors."""
        return self.embed(texts)

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.llm is None:
            logger.warning("Embedding client is None — returning zero vectors")
            return [[0.0] * 1536 for _ in texts]
        # If the configured embedding model isn't available on this provider,
        # stop retrying per-call and return zero vectors (semantic search
        # degrades to lexical) instead of spamming 404s.
        if self._failed:
            return [[0.0] * 1536 for _ in texts]
        try:
            response = self.llm.embeddings.create(model=self.model, input=texts)
            vectors = [item.embedding for item in response.data]
            return vectors
        except Exception as e:
            logger.warning("Embedding call failed (%d texts): %s", len(texts), e)
            self._failed = True
            dims = 1536
            return [[0.0] * dims for _ in texts]
