"""Recherche lexicale BM25 (mots exacts) et fusion de classements (RRF).

Les embeddings ratent parfois des passages courts ou très « listes » (ex. « 5 à 10 quiz par chapitre ») ;
BM25 les retrouve grâce aux mots rares partagés avec la question. La fusion RRF combine les deux
classements sans avoir à rendre leurs scores comparables.
"""

import math
import re
import unicodedata
from collections import Counter

# Mots trop fréquents pour aider à discriminer les passages (sans accents, comme après normalisation).
STOPWORDS = set("""
a au aux avec ce ces cette dans de des du elle elles en est et etre il ils je la le les leur leurs
lui ma mais me meme mes mon ne nos notre nous on ou par pas pour qu que qui sa se ses son sont sur
ta te tes ton tu un une vos votre vous y c d j l m n s t quel quelle quels quelles comment pourquoi
quand combien ou doit doivent peut faut fait faire sert servent cela ca ont a-t-il est-ce
""".split())


def tokenize(text: str) -> list[str]:
    """Minuscules, sans accents, sans mots vides, pluriels simples ramenés au singulier."""
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    tokens = []
    for tok in re.findall(r"[a-z0-9]+", text):
        if tok in STOPWORDS or (len(tok) < 2 and not tok.isdigit()):
            continue
        if len(tok) > 4 and tok[-1] in "sx":
            tok = tok[:-1]
        tokens.append(tok)
    return tokens


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_len = (sum(self.lengths) / len(self.lengths)) if self.docs else 0.0
        df = Counter(term for d in self.docs for term in d)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def __len__(self) -> int:
        return len(self.docs)

    def scores(self, query: str) -> list[float]:
        terms = tokenize(query)
        out = []
        for doc, length in zip(self.docs, self.lengths):
            s = 0.0
            for t in terms:
                tf = doc.get(t, 0)
                if tf:
                    norm = tf + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                    s += self.idf[t] * tf * (self.k1 + 1) / norm
            out.append(s)
        return out


def rrf(rankings: list[list[str]], k: int = 60) -> list[tuple[str, float]]:
    """Reciprocal Rank Fusion : score(id) = Σ 1 / (k + rang). Renvoie les ids triés."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
