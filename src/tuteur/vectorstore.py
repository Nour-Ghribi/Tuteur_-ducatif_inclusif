"""Base vectorielle : embeddings multilingues (sentence-transformers) + ChromaDB persistant,
avec recherche hybride optionnelle (embeddings + BM25, fusion RRF)."""

from dataclasses import dataclass
from functools import cached_property

import chromadb

from tuteur.chunking import Chunk
from tuteur.config import Settings, get_settings
from tuteur.lexical import BM25, rrf


@dataclass
class SearchResult:
    id: str
    text: str
    metadata: dict
    score: float  # dense : similarité cosinus (1 = identique) ; hybride : score RRF


class VectorStore:
    def __init__(self, settings: Settings | None = None, client: chromadb.ClientAPI | None = None):
        self.settings = settings or get_settings()
        self.client = client or chromadb.PersistentClient(path=str(self.settings.chroma_dir))
        self.collection = self.client.get_or_create_collection(
            self.settings.collection, metadata={"hnsw:space": "cosine"}
        )

    @cached_property
    def _model(self):
        from sentence_transformers import SentenceTransformer  # import lent : chargé à la demande

        return SentenceTransformer(self.settings.embedding_model)

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        # Les modèles E5 attendent un préfixe "query: " ou "passage: ".
        if "e5" in self.settings.embedding_model.lower():
            texts = [f"{kind}: {t}" for t in texts]
        return self._model.encode(texts, normalize_embeddings=True).tolist()

    def add(self, chunks: list[Chunk], batch_size: int = 64) -> int:
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            self.collection.upsert(
                ids=[c.id for c in batch],
                documents=[c.text for c in batch],
                metadatas=[c.metadata for c in batch],
                embeddings=self._embed([c.text for c in batch], "passage"),
            )
        return len(chunks)

    def search(
        self, query: str, k: int | None = None, where: dict | None = None, mode: str | None = None
    ) -> list[SearchResult]:
        """mode « dense » : embeddings seuls ; « hybride » : embeddings + BM25 fusionnés par RRF.
        En hybride, `score` est le score RRF (sert à classer, pas une similarité)."""
        k = k or self.settings.top_k
        mode = mode or self.settings.search_mode
        if mode == "dense":
            return self._dense(query, k, where)
        if mode != "hybride":
            raise ValueError(f"Mode de recherche inconnu : {mode}")

        pool = max(self.settings.hybrid_pool, k)
        dense = self._dense(query, pool, where)
        lexical = self._lexical(query, pool, where)
        by_id = {r.id: r for r in dense + lexical}
        fused = rrf([[r.id for r in dense], [r.id for r in lexical]])[:k]
        return [SearchResult(id=i, text=by_id[i].text, metadata=by_id[i].metadata, score=s) for i, s in fused]

    def _dense(self, query: str, k: int, where: dict | None) -> list[SearchResult]:
        res = self.collection.query(
            query_embeddings=self._embed([query], "query"),
            n_results=min(k, max(self.collection.count(), 1)),
            where=where,
        )
        return [
            SearchResult(id=i, text=d, metadata=m, score=1 - dist)
            for i, d, m, dist in zip(
                res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]

    def _lexical(self, query: str, k: int, where: dict | None) -> list[SearchResult]:
        if where and any(k_.startswith("$") or isinstance(v, dict) for k_, v in where.items()):
            raise ValueError("Le mode hybride n'accepte que des filtres d'égalité simples, ex. {'doc_id': '...'}")
        ids, docs, metas, index = self._bm25()
        scored = sorted(
            (
                (s, i)
                for i, s in enumerate(index.scores(query))
                if s > 0 and all(metas[i].get(f) == v for f, v in (where or {}).items())
            ),
            reverse=True,
        )[:k]
        return [SearchResult(id=ids[i], text=docs[i], metadata=metas[i], score=s) for s, i in scored]

    def _bm25(self):
        """Index BM25 sur tous les chunks, reconstruit si la collection a changé."""
        count = self.collection.count()
        if getattr(self, "_bm25_cache", None) is None or self._bm25_cache[0] != count:
            data = self.collection.get(include=["documents", "metadatas"])
            self._bm25_cache = (count, data["ids"], data["documents"], data["metadatas"], BM25(data["documents"]))
        return self._bm25_cache[1:]

    def get_pages(self, doc_id: str, pages: list[int]) -> list[SearchResult]:
        """Récupère tous les chunks de pages données (pour générer un quiz sur un chapitre)."""
        res = self.collection.get(
            where={"$and": [{"doc_id": doc_id}, {"page": {"$in": pages}}]}
        )
        out = [SearchResult(id=i, text=d, metadata=m, score=1.0)
               for i, d, m in zip(res["ids"], res["documents"], res["metadatas"])]
        return sorted(out, key=lambda r: (r.metadata["page"], int(r.id.rsplit("-c", 1)[1])))

    def documents(self) -> dict[str, str]:
        """doc_id -> nom du fichier source."""
        metas = self.collection.get(include=["metadatas"])["metadatas"]
        return {m["doc_id"]: m["source"] for m in metas}

    def delete_document(self, doc_id: str) -> None:
        self.collection.delete(where={"doc_id": doc_id})
