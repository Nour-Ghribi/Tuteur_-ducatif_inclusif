# Interface dynamique et accessible

React + TypeScript (Vite). L'interface **n'exécute jamais de code venant d'un modèle** : le backend renvoie
une spécification (`UISpec`) validée, et le frontend ne sait afficher que 17 composants prédéfinis.

```
backend (Pydantic UISpec) ──JSON──► parseUI (zod) ──► BlockView ──► composants accessibles
                                       │ bloc inconnu/mal formé → écarté + message, jamais rendu
                                       └ spec illisible → bloc de secours (« affichage sûr »)
```

| Dossier | Rôle |
|---|---|
| `src/ui-schema/` | schéma zod = miroir de `backend/agentic/.../schemas/ui.py` ; `__fixtures__/` = **vraies** réponses du backend |
| `src/renderer/` | `BlockView` : seule table type → composant ; `ResponseMeta` : ce qui a été (ou non) vérifié, données simulées |
| `src/components/` | texte, quiz, flashcards, étapes, comparaison, carte conceptuelle, rapport, images |
| `src/a11y/` | préférences **déclarées** (jamais déduites) : texte simple/court, affichage épuré, lecteur d'écran, contraste, daltonisme, taille |
| `src/i18n/` | toutes les chaînes en français ; les codes du backend (`reason_code`, `message_code`…) sont traduits ici |
| `src/api/` | client HTTP (jeton de développement en `sessionStorage`) ; les blocs n'appellent jamais le réseau |

## Accessibilité

HTML sémantique (`fieldset/legend`, `table/caption/th scope`, `ol`, `progress`), un seul `h1`, lien d'évitement,
focus visible, cibles ≥ 44 px, clavier complet (flashcards : Entrée/Espace + flèches), zones `aria-live` pour
les retours, figures avec texte alternatif obligatoire (ou texte de remplacement explicite), carte conceptuelle
et graphiques **toujours doublés d'une version texte/tableau**, `prefers-reduced-motion`, thème sombre/clair,
contraste élevé et taille de texte réglables. Les tests exécutent axe-core sur chaque réponse réelle du backend.

## Commandes

```bash
npm install
npm run dev          # http://localhost:5173 (proxy /api → http://127.0.0.1:8000)
npm test             # contrat backend↔frontend, accessibilité (axe), comportement, cas malformés
npm run build        # tsc + build de production
npm run fixtures     # régénère les réponses du backend (Python requis : voir backend/agentic)
```

`http://localhost:5173/gallery.html` (développement seulement) affiche tous les composants avec les vraies
réponses simulées ; paramètres : `?contrast=1&scale=1.5&reduced=1&color=deuteranopia&only=quiz,concept_map`.

## Limites

Contraste des couleurs : vérifié par conception (variables CSS, mode contraste élevé), pas mesuré
automatiquement (jsdom n'a pas de rendu). Aucun test avec un lecteur d'écran réel (NVDA/VoiceOver) n'a été fait.
