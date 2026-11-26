"""Vérification des citations [p. N] : chaque page citée doit être celle d'un passage fourni au LLM.

Exemple d'erreur réelle : « [p. 8] » pour un PDF de 4 pages — le modèle avait pris le numéro de
section « 8. Valeur ajoutée… » pour un numéro de page. Montrer une fausse page à un élève est pire
que ne rien citer : on retire donc les citations invalides avant d'afficher la réponse.
"""

import re
from dataclasses import dataclass, field

# [p. 3]  [p.3]  [p. 1, 3]  [p. 1 ; p. 2]  [pages 2-3]  [p. 1–2]
# et 【p. 1】 : crochets « lenticulaires » que les modèles gpt-oss utilisent spontanément.
_CITATION = re.compile(r"[\[【]\s*(?:p\.?|pages?)[\s  ]*\d[^\]】]*[\]】]", re.I)


def cited_pages(citation: str) -> list[int]:
    pages = []
    for a, b in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", citation):
        pages.extend(range(int(a), int(b) + 1) if b and int(b) - int(a) < 50 else [int(a)])
    return pages


@dataclass
class CitationCheck:
    cited: list[int] = field(default_factory=list)  # toutes les pages citées, dans l'ordre
    invalid: list[int] = field(default_factory=list)  # pages citées absentes des passages fournis

    @property
    def n_citations(self) -> int:
        return len(self.cited)

    @property
    def validity(self) -> float | None:
        return 1 - len(self.invalid) / len(self.cited) if self.cited else None


def check_citations(text: str, allowed_pages: set[int]) -> CitationCheck:
    check = CitationCheck()
    for m in _CITATION.finditer(text):
        for page in cited_pages(m.group()):
            check.cited.append(page)
            if page not in allowed_pages:
                check.invalid.append(page)
    return check


def strip_invalid_citations(text: str, allowed_pages: set[int]) -> str:
    """Garde les pages valides d'une citation (réécrite au format [p. N]), supprime la citation
    si aucune ne l'est."""
    def fix(m: re.Match) -> str:
        valid = [p for p in cited_pages(m.group()) if p in allowed_pages]
        return "[p. " + ", ".join(map(str, dict.fromkeys(valid))) + "]" if valid else ""

    out = _CITATION.sub(fix, text)
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", re.sub(r"[ \t]{2,}", " ", out))  # espaces laissés par une suppression
