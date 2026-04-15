"""
Plugin Embeddings - ChromaDB vector store for semantic search.
Uses Ollama's nomic-embed-text model for local embedding generation.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import os
os.environ["ANONYMIZED_TELEMETRY"] = "False"

import chromadb
from chromadb.config import Settings
import httpx

from config import (
    CHROMA_DB_PATH, CHROMA_COLLECTION_NAME, EMBEDDING_MODEL,
    EMBEDDING_BATCH_SIZE, OLLAMA_BASE_URL, OLLAMA_KEEP_ALIVE,
)


class PluginEmbeddingStore:
    """Manages ChromaDB collection for semantic plugin search."""

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=str(CHROMA_DB_PATH),
            settings=Settings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def _embed_via_ollama(self, texts: list[str]) -> list[list[float]]:
        """Get embeddings from Ollama's embedding model (always local)."""
        from src.llm_client import get_chat_client
        client = get_chat_client()
        return client.embed(texts, model=EMBEDDING_MODEL, ollama_url=OLLAMA_BASE_URL)

    def _build_document(self, plugin: dict) -> str:
        """Build a rich text document from plugin metadata for embedding."""
        parts = [
            f"Plugin: {plugin.get('display_name') or plugin.get('name', '')}",
        ]
        if plugin.get("developer"):
            parts.append(f"Developer: {plugin['developer']}")
        if plugin.get("category"):
            parts.append(f"Category: {plugin['category']}")
        if plugin.get("subcategory"):
            parts.append(f"Subcategory: {plugin['subcategory']}")
        if plugin.get("plugin_type"):
            parts.append(f"Type: {plugin['plugin_type']}")
        if plugin.get("subtype"):
            parts.append(f"Subtype: {plugin['subtype']}")
        if plugin.get("emulation_of"):
            parts.append(f"Emulation of: {plugin['emulation_of']}")
        if plugin.get("description"):
            parts.append(f"Description: {plugin['description']}")
        if plugin.get("specialty"):
            parts.append(f"Specialty: {plugin['specialty']}")
        if plugin.get("best_used_for"):
            parts.append(f"Best used for: {plugin['best_used_for']}")
        if plugin.get("character"):
            parts.append(f"Character: {plugin['character']}")
        if plugin.get("signal_chain_position"):
            parts.append(f"Signal chain: {plugin['signal_chain_position']}")
        if plugin.get("tags"):
            parts.append(f"Tags: {plugin['tags']}")
        if plugin.get("notes"):
            parts.append(f"Notes: {plugin['notes']}")
        if plugin.get("is_own_plugin"):
            parts.append(f"Own plugin ({plugin.get('own_brand', 'custom')})")

        return "\n".join(parts)

    def _build_metadata(self, plugin: dict) -> dict:
        """Build ChromaDB-compatible metadata dict (strings/ints/floats only)."""
        meta = {}
        for key in [
            "name", "display_name", "developer", "format", "install_scope",
            "plugin_type", "category", "subcategory", "subtype",
            "emulation_of", "character", "signal_chain_position",
            "classification_confidence", "own_brand",
        ]:
            val = plugin.get(key)
            if val is not None:
                meta[key] = str(val)

        meta["is_own_plugin"] = 1 if plugin.get("is_own_plugin") else 0
        meta["needs_review"] = 1 if plugin.get("needs_review") else 0

        if plugin.get("id"):
            meta["plugin_id"] = int(plugin["id"])

        return meta

    def upsert_plugins(self, plugins: list[dict]) -> int:
        """
        Embed and upsert a list of plugins into ChromaDB.
        Returns the number of plugins upserted.
        """
        if not plugins:
            return 0

        total = 0
        for i in range(0, len(plugins), EMBEDDING_BATCH_SIZE):
            batch = plugins[i : i + EMBEDDING_BATCH_SIZE]

            ids = []
            documents = []
            metadatas = []

            for p in batch:
                # Use a stable ID: prefer DB id, fall back to file_name_format_scope
                if p.get("id"):
                    doc_id = f"plugin_{p['id']}"
                else:
                    doc_id = f"{p.get('file_name', p.get('name', 'unknown'))}_{p.get('format', '')}_{p.get('install_scope', '')}".lower()
                    doc_id = doc_id.replace(" ", "_")

                ids.append(doc_id)
                documents.append(self._build_document(p))
                metadatas.append(self._build_metadata(p))

            # Get embeddings from Ollama
            embeddings = self._embed_via_ollama(documents)

            self.collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )

            total += len(batch)
            print(f"  Embedded {total}/{len(plugins)} plugins...")

        return total

    def search(self, query: str, n_results: int = 15, where: dict = None) -> list[dict]:
        """
        Semantic search for plugins matching a natural language query.
        Returns list of dicts with: id, document, metadata, distance.
        """
        # Embed the query
        query_embedding = self._embed_via_ollama([query])[0]

        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        results = self.collection.query(**kwargs)

        output = []
        if results and results["ids"] and results["ids"][0]:
            for idx in range(len(results["ids"][0])):
                output.append({
                    "id": results["ids"][0][idx],
                    "document": results["documents"][0][idx],
                    "metadata": results["metadatas"][0][idx],
                    "distance": results["distances"][0][idx],
                })

        return output

    def delete_all(self):
        """Clear the entire collection (for full rescan)."""
        self.client.delete_collection(CHROMA_COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=CHROMA_COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        """Return the number of documents in the collection."""
        return self.collection.count()


if __name__ == "__main__":
    store = PluginEmbeddingStore()
    print(f"ChromaDB collection '{CHROMA_COLLECTION_NAME}' has {store.count()} documents.")
