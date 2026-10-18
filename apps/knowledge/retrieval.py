"""Verified TF-IDF ranking, forked from Prototype; only immutable DB-derived chunks.

Algorithm, expansion, feature cap, threshold and tie ordering are unchanged.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
import math
import re
from .evidence import KnowledgeEvidence, utcnow

def _char_wb_ngrams(text: str) -> Counter[str]:
    """Equivalent token shape to sklearn analyzer='char_wb', ngram_range=(2, 4)."""
    counts: Counter[str] = Counter()
    for word in re.sub(r"\s\s+", " ", text.lower()).split():
        padded = f" {word} "
        for size in (2, 3, 4):
            for start in range(max(0, len(padded) - size + 1)):
                counts[padded[start:start + size]] += 1
    return counts


class _PortableTfidf:
    def __init__(self, texts: list[str], max_features: int = 2000):
        rows = [_char_wb_ngrams(text) for text in texts]
        corpus_frequency: Counter[str] = Counter()
        document_frequency: Counter[str] = Counter()
        for row in rows:
            corpus_frequency.update(row)
            document_frequency.update(row.keys())
        chosen = sorted(corpus_frequency, key=lambda term: (-corpus_frequency[term], term))[:max_features]
        self.idf = {term: math.log((1 + len(texts)) / (1 + document_frequency[term])) + 1
                    for term in chosen}
        self.rows = [self.vectorize_counts(row) for row in rows]

    def vectorize_counts(self, counts: Counter[str]) -> dict[str, float]:
        vector = {term: frequency * self.idf[term] for term, frequency in counts.items()
                  if term in self.idf}
        norm = math.sqrt(sum(value * value for value in vector.values()))
        return {term: value / norm for term, value in vector.items()} if norm else {}

    def scores(self, query: str) -> list[float]:
        query_vector = self.vectorize_counts(_char_wb_ngrams(query))
        return [sum(value * query_vector.get(term, 0.0) for term, value in row.items())
                for row in self.rows]


class KnowledgeService:
    EXPANSIONS = {
        "不吃": "摄食 食欲 投喂", "不食": "摄食 投喂", "不吃料": "摄食 饲料 投喂",
        "浮头": "缺氧 溶氧 水面", "白点": "爱德华氏 脓肿 白点 气泡",
        "红": "充血 赤鳍", "烂": "溃烂 水霉", "死": "死亡 死亡率",
        "出血": "充血 赤鳍", "浑浊": "悬浮物 藻类 透明度",
        "苗": "玻璃鳗 鳗苗 黑仔鳗 elver",
    }

    def __init__(self, chunks, *, disease_names=(), source_id="legacy:eel_knowledge.json",
                 source_version="1.0", backend="portable"):
        self.chunks = [dict(item) for item in chunks]
        self.disease_names = tuple(disease_names)
        self.source_id, self.source_version = source_id, source_version
        self._build_index(backend)

    def _build_index(self, backend: str):
        self.backend = backend
        self._index = None
        if backend == "portable":
            self._index = _PortableTfidf([item["text"] for item in self.chunks])
        elif backend == "sklearn":
            try:
                from sklearn.feature_extraction.text import TfidfVectorizer
                vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), max_features=2000)
                matrix = vectorizer.fit_transform([item["text"] for item in self.chunks])
                self._index = (vectorizer, matrix)
            except ImportError:
                self.backend = "keyword"
        elif backend != "keyword":
            raise ValueError("backend must be portable, sklearn or keyword")

    def _intent(self, text: str) -> tuple[bool, bool]:
        lowered = text.lower()
        disease_terms = ("疾病", "病害", "鱼病", "患病", "感染", "寄生虫", "治疗",
                         "用药", "药物", "症状", "病原", "白点", "出血", "溃烂", "鳃丝", "体表")
        named_disease = any(
            name and name in lowered
            for disease_name in self.disease_names
            for name in (disease_name.split("(")[0].strip().lower(),
                         disease_name.split("(")[0].strip().removesuffix("病").lower())
            if len(name) >= 2
        )
        disease_intent = named_disease or any(term in lowered for term in disease_terms)
        water_intent = any(term in lowered for term in (
            "水质", "溶氧", "溶解氧", "缺氧", "氧气", "水温", "ph", "酸碱", "氨氮"))
        return disease_intent, water_intent

    def _adjust_score(self, index: int, score: float, *, disease_intent: bool,
                      water_intent: bool) -> float:
        if score <= 0:
            return score
        category = self.chunks[index]["type"]
        if category == "disease":
            return score + 0.12 if disease_intent else score * 0.1
        if water_intent and category == "water_quality":
            return score + 0.15
        if water_intent and category == "relationships":
            return score + 0.28
        return score

    def search(self, query: str, *, top_k: int = 5, retrieved_at: datetime | None = None,
               intent_text: str | None = None
               ) -> tuple[KnowledgeEvidence, ...]:
        if top_k < 1:
            return ()
        timestamp = retrieved_at or utcnow()
        disease_intent, water_intent = self._intent(query if intent_text is None else intent_text)
        if self.backend == "keyword":
            ranked = self._keyword_scores(query, top_k, disease_intent=disease_intent,
                                          water_intent=water_intent)
        else:
            expanded = query
            for key, value in self.EXPANSIONS.items():
                if key in query:
                    expanded += " " + value
            if self.backend == "portable":
                scores = self._index.scores(expanded)
            else:
                vectorizer, matrix = self._index
                scores = (matrix @ vectorizer.transform([expanded]).T).toarray().flatten().tolist()
            query_lower = query.lower()
            for index, chunk in enumerate(self.chunks):
                for keyword in chunk.get("keywords", []):
                    word = keyword.lower()
                    if len(word) >= 2 and word in query_lower:
                        scores[index] += 0.3
                        break
            scores = [self._adjust_score(i, score, disease_intent=disease_intent,
                                         water_intent=water_intent)
                      for i, score in enumerate(scores)]
            ranked = [(i, scores[i]) for i in sorted(range(len(scores)),
                      key=lambda i: (scores[i], i), reverse=True)[:top_k] if scores[i] >= 0.04]
        return tuple(KnowledgeEvidence(
            evidence_id=self.chunks[i]["id"], text=self.chunks[i]["text"],
            category=self.chunks[i]["type"], score=float(score),
            source_id=self.chunks[i].get("source_id", self.source_id),
            source_title=self.chunks[i].get("source_title"),
            source_version=self.chunks[i].get("source_version", self.source_version), retrieved_at=timestamp,
        ) for i, score in ranked)

    def _keyword_scores(self, query: str, top_k: int, *, disease_intent: bool,
                        water_intent: bool) -> list[tuple[int, float]]:
        lowered = query.lower()
        scored = []
        for index, chunk in enumerate(self.chunks):
            score = sum(2 for keyword in chunk.get("keywords", []) if keyword.lower() in lowered)
            if any(word in lowered for word in chunk["text"][:80].split()):
                score += 1
            if score:
                scored.append((index, self._adjust_score(
                    index, float(score), disease_intent=disease_intent,
                    water_intent=water_intent)))
        scored.sort(key=lambda item: -item[1])
        return scored[:top_k]
