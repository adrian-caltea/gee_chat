import os
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150
EMBED_MODEL = "all-MiniLM-L6-v2"

class RAGIndex:
    def __init__(self, txt_path="./data/training.txt"):
        self.txt_path = txt_path
        self.model = SentenceTransformer(EMBED_MODEL)
        self.chunks = []
        self.embeddings = None
        self.index = None
        self._build_index()

    def _read_text(self):
        with open(self.txt_path, "r", encoding="utf-8") as f:
            return f.read()

    def _chunk_text(self, text):
        chunks = []
        i = 0
        L = len(text)
        while i < L:
            end = min(i + CHUNK_SIZE, L)
            chunk = text[i:end].strip()
            if chunk:
                chunks.append(chunk)
            i += CHUNK_SIZE - CHUNK_OVERLAP
        return chunks

    def _build_index(self):
        text = self._read_text()
        self.chunks = self._chunk_text(text)
        if not self.chunks:
            raise ValueError("No chunks created from training text. Check training.txt")
        self.embeddings = self.model.encode(self.chunks, convert_to_numpy=True, show_progress_bar=True)
        faiss.normalize_L2(self.embeddings)
        d = self.embeddings.shape[1]
        self.index = faiss.IndexFlatIP(d)
        self.index.add(self.embeddings)

    def query(self, query_text, top_k=6):
        q_emb = self.model.encode([query_text], convert_to_numpy=True)
        faiss.normalize_L2(q_emb)
        D, I = self.index.search(q_emb, top_k)
        results = []
        for idx in I[0]:
            if 0 <= idx < len(self.chunks):
                results.append(self.chunks[idx])
        return results