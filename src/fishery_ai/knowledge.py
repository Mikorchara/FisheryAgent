"""Portable TF-IDF baseline and the production keyword fallback."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import json
import math
import re

from .contracts import KnowledgeEvidence, utcnow


def chunk_knowledge(kg: dict) -> list[dict]:
    """Preserve the production c400b7a chunk IDs, text and keywords."""
    chunks: list[dict] = []
    for key, data in kg["water_quality"].items():
        unit = data.get("unit", "")
        safe = data.get("optimal_range", data.get("safe_range", []))
        guidance = data.get("guidance", {})
        body = f"水质参数 {key}：适宜范围 {safe[0]}-{safe[1]}{' ' + str(unit) if unit else ''}。"
        if guidance:
            body += " " + " ".join(f"{k}: {v}" for k, v in guidance.items())
        chunks.append({"id": f"wq_{key}", "type": "water_quality", "text": body, "keywords": [key]})

    for stage in kg["life_cycle"]["stages"]:
        kp = stage.get("key_params", {})
        params_text = "；".join(f"{k}: {v}" for k, v in kp.items()) if kp else ""
        parts = [f"鳗鲡生长阶段：{stage['name']}"]
        for field, label in (("size", "规格"), ("duration", "周期"), ("habitat", "环境"), ("note", "备注")):
            if stage.get(field):
                parts.append(f"{label}：{stage[field]}")
        body = "。".join(parts) + "。" + params_text
        chunks.append({"id": f"stage_{stage['name']}", "type": "life_cycle", "text": body,
                       "keywords": [stage["name"]]})

    for disease in kg["diseases"]:
        body = (
            f"病害：{disease['name']}。病原体：{disease['pathogen']}。"
            f"症状：{'、'.join(disease['symptoms'])}。"
            f"高发条件：{'、'.join(disease['triggers'])}。"
            f"治疗：{'；'.join(disease['treatment'])}。"
            f"预防：{'；'.join(disease['prevention'])}。"
        )
        chunks.append({"id": f"disease_{disease['name']}", "type": "disease", "text": body,
                       "keywords": disease["symptoms"] + disease["triggers"]})

    feeding = kg["feeding_management"]
    chunks.append({"id": "feeding_rate", "type": "feeding", "text": "投喂率与水温关系：" + "；".join(
        f"{k.replace('_', ' ')}: {v}" for k, v in feeding["feeding_rate_by_temperature"].items()),
        "keywords": ["投喂", "水温", "饲料"]})
    chunks.append({"id": "feeding_principles", "type": "feeding", "text": "投喂原则：" + "；".join(
        feeding["key_principles"]), "keywords": ["投喂", "原则"]})
    chunks.append({"id": "feeding_freq", "type": "feeding", "text": "投喂频率：" + "；".join(
        f"{k}: {v}" for k, v in feeding["feeding_frequency"].items()), "keywords": ["投喂", "频率"]})

    environment = kg["environmental_management"]
    for key in ("water_exchange", "aeration", "light_management", "stocking_density", "grading"):
        data = environment[key]
        body = f"{key}："
        if isinstance(data, dict):
            body += "；".join(f"{k}: {v}" for k, v in data.items() if k != "method")
            if "method" in data:
                body += "。方法：" + "、".join(data["method"])
        else:
            body += str(data)
        chunks.append({"id": f"env_{key}", "type": "environment", "text": body, "keywords": [key]})

    for name, problem in kg["common_problems"].items():
        body = (f"常见问题 {name}：可能原因——{'、'.join(problem['causes'])}。"
                f"处理措施——{'；'.join(problem['actions'])}。")
        chunks.append({"id": f"problem_{name}", "type": "problem", "text": body,
                       "keywords": problem["causes"]})

    relationships = kg["key_relationships"]
    chunks.append({"id": "relationships", "type": "relationships", "text": "水质耦合关系：" + "；".join(
        f"{k}: {v}" for k, v in relationships.items()), "keywords": list(relationships.keys())})
    return chunks


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

    def __init__(self, knowledge_path: Path, *, backend: str = "portable"):
        self.kg = json.loads(knowledge_path.read_text(encoding="utf-8"))
        self.chunks = chunk_knowledge(self.kg)
        self.source_id = "legacy:eel_knowledge.json"
        self.source_version = str(self.kg.get("version", "unknown"))
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

    def search(self, query: str, *, top_k: int = 5, retrieved_at: datetime | None = None
               ) -> tuple[KnowledgeEvidence, ...]:
        if top_k < 1:
            return ()
        timestamp = retrieved_at or utcnow()
        if self.backend == "keyword":
            ranked = self._keyword_scores(query, top_k)
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
                    if word in query_lower or any(query_lower[j:j + 2] in word
                                                  for j in range(len(query_lower) - 1)):
                        scores[index] += 0.3
                        break
            ranked = [(i, scores[i]) for i in sorted(range(len(scores)),
                      key=lambda i: (scores[i], i), reverse=True)[:top_k] if scores[i] >= 0.04]
        return tuple(KnowledgeEvidence(
            evidence_id=self.chunks[i]["id"], text=self.chunks[i]["text"],
            category=self.chunks[i]["type"], score=float(score),
            source_id=self.source_id, source_title=None,
            source_version=self.source_version, retrieved_at=timestamp,
        ) for i, score in ranked)

    def _keyword_scores(self, query: str, top_k: int) -> list[tuple[int, float]]:
        lowered = query.lower()
        scored = []
        for index, chunk in enumerate(self.chunks):
            score = sum(2 for keyword in chunk.get("keywords", []) if keyword.lower() in lowered)
            if any(word in lowered for word in chunk["text"][:80].split()):
                score += 1
            if score:
                scored.append((index, float(score)))
        scored.sort(key=lambda item: -item[1])
        return scored[:top_k]
