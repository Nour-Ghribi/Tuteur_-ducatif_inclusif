# MVP local — GenAI/RAG + LinUCB

## Statut vérifié

- L'algorithme disjoint LinUCB est implémenté avec 5 actions, normalisation des 19 variables, constante, exploration UCB et coûts d'action.
- Un entraînement synthétique limité a été exécuté avec le protocole figé `configs/linucb_demo_v1.json`.
- Le checkpoint `models/linucb_demo_v1.json` est réellement entraîné, signé par SHA-256, chargé et validé contre les versions du schéma, des variables et des actions.
- L'inférence LinUCB est la décision principale du MVP. Le système règle-based est uniquement un repli explicite et visible.
- Le parcours mock complet est testé hors ligne avec les vrais services d'orchestration et SQLite.
- Le client LLM réel et le RAG existants sont conservés et reliés aux cinq stratégies A0–A4.
- Aucun appel à un fournisseur LLM externe n'a été exécuté pendant cette livraison. Sa connectivité reste à vérifier avec les identifiants de l'utilisateur.
- Les effets d'intervention synthétiques sont des hypothèses de démonstration. L'efficacité éducative réelle n'est pas établie.

## Lancer la démonstration mock sous Windows

PowerShell :

```powershell
cd C:\Users\nourg\Desktop\RL_ed\integration_genai_rl_mvp
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,mvp]"
Copy-Item .env.example .env
$env:ADAPTIVE_MODE = "mock"
streamlit run app.py
```

Le navigateur ouvre normalement `http://localhost:8501`. Sélectionner `MOCK DEMO`, générer une question, choisir une mauvaise réponse, consulter la décision LinUCB et répondre à la question de récupération. L'historique est conservé dans `data/adaptive_tutor.sqlite3`.

## Configurer un vrai fournisseur LLM

Le client accepte toute API compatible OpenAI. Modifier `.env`, sans jamais versionner de secret :

```dotenv
ADAPTIVE_MODE=real
ADAPTIVE_DB_PATH=data/adaptive_tutor.sqlite3
ADAPTIVE_POLICY_CHECKPOINT=models/linucb_demo_v1.json

LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=replace-with-an-available-model
LLM_API_KEY=replace-with-your-secret
LLM_TEMPERATURE=0.3

EMBEDDING_MODEL=intfloat/multilingual-e5-small
CHROMA_DIR=data/chroma
COLLECTION=cours
SEARCH_MODE=hybride
```

Exemples de `LLM_BASE_URL` : Ollama `http://localhost:11434/v1`, Groq `https://api.groq.com/openai/v1`, OpenAI `https://api.openai.com/v1`. Pour Gemini, utiliser l'URL OpenAI-compatible, le modèle et la clé fournis par Google. Les noms de modèles et quotas changent : utiliser un modèle actuellement disponible chez le fournisseur choisi.

Indexer au moins un cours avant le lancement réel :

```powershell
tuteur ingest data\raw\photosynthese.md
$env:ADAPTIVE_MODE = "real"
streamlit run app.py
```

Le sélecteur `REAL LLM` dans la barre latérale est explicite. Une clé absente, un fournisseur inaccessible, un modèle invalide ou un index vide produit une erreur visible ; l'application ne substitue jamais silencieusement le mock au vrai LLM.

## Checklist manuelle

Pour tester le parcours général :

1. Générer un quiz depuis le cours.
2. Soumettre une mauvaise réponse.
3. Vérifier `Politique: LinUCB`, la version et `provenance: simulation_trained`.
4. Vérifier que la remédiation cite uniquement une page récupérée.
5. Soumettre la question de suivi et vérifier l'issue persistée.
6. Ouvrir l'audit de session et vérifier la stratégie, la politique, le mécanisme d'affectation et l'issue.

Pour inspecter A0–A4 de manière déterministe, exécuter :

```powershell
pytest tests\test_adaptive_mvp.py -q
```

Les cinq cas paramétrés contrôlent : A0 indice sans réponse explicite, A1 explication simplifiée, A2 exemple résolu, A3 QCM étayé et A4 révision ciblée. Ils passent tous par `Tutor.adaptive_remediate`, les prompts versionnés, les schémas Pydantic et la fixture RAG hors ligne.

## Vérifications développeur

```powershell
python scripts\train_demo_linucb.py
pytest -q
ruff check app.py scripts\train_demo_linucb.py src\tuteur\adaptive src\tuteur\demo_llm.py src\tuteur\generation.py tests\test_adaptive_mvp.py
python -m compileall -q app.py src scripts
```

L'exécution du script d'entraînement réécrit le checkpoint à partir du protocole figé. L'horodatage et donc le hash du fichier peuvent changer, mais les paramètres appris et les décisions restent déterministes pour le même protocole.

## Limites de V1

LinUCB ne se met pas à jour automatiquement avec les interactions réelles. Chaque décision conserve le contexte 19D, l'action, la livraison, le mécanisme d'affectation, la version de politique et l'issue observée ou en attente. Une future étude contrôlée définira comment apprendre sur ces retours sans confondre corrélation et effet causal.
