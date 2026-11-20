# Protocole du checkpoint LinUCB de démonstration

## Portée scientifique

Ce checkpoint sert uniquement à démontrer une chaîne logicielle réelle d'inférence contextual-bandit sur le contrat plateforme 19D. Les contextes, effets d'action et récompenses sont synthétiques et explicitement hypothétiques. Ils ne sont dérivés ni d'EdNet, ni d'élèves réels, ni des expériences M1–M6.

La définition a été figée avant l'évaluation dans `configs/linucb_demo_v1.json` : seed d'entraînement `20261120`, seed d'évaluation indépendante `20261220`, budget `15 000`, évaluation `5 000`, ridge `10`, exploration `0.75` et coûts `[0.01, 0.01, 0.03, 0.02, 0.03]`. Aucun seed n'a été sélectionné après observation du jeu d'évaluation.

## Algorithme et contrat

Le modèle est un LinUCB disjoint, soit une matrice et un vecteur par action. Les 19 valeurs sont standardisées avec les statistiques du jeu synthétique d'entraînement, puis une constante est ajoutée en interne. Le score utilisé est :

`estimation de récupération + alpha × incertitude UCB − coût de l'action`.

Les actions et leur ordre sont figés : A0 indice guidé, A1 explication simplifiée, A2 exemple résolu, A3 QCM étayé, A4 révision ciblée. Le chargeur refuse un checkpoint dont le hash, la version 19D, l'ordre des variables ou l'ordre des actions diffère.

## Résultat de l'exécution figée

Sur les 5 000 contextes synthétiques indépendants, la récompense attendue hypothétique est :

| Politique | Récompense attendue | Regret moyen |
|---|---:|---:|
| LinUCB | 0.57795 | 0.02593 |
| Baseline règle-based | 0.56040 | 0.04347 |
| Action constante la mieux placée | 0.56911 | 0.03476 |
| Aléatoire | 0.50962 | 0.09426 |
| Oracle synthétique (borne haute) | 0.60388 | 0.00000 |

Ces nombres caractérisent uniquement le simulateur défini dans `src/tuteur/adaptive/synthetic.py`. Ils ne prédisent pas un gain réel. Le rapport machine complet est `results/linucb_demo_v1_evaluation.json`. Après rechargement, les 5 000 décisions sont identiques à celles prises avant sauvegarde.

## Apprentissage futur

V1 journalise les retours réels mais n'effectue aucune mise à jour en ligne. Une phase ultérieure devra pré-enregistrer le mécanisme d'affectation, les critères d'éligibilité, le traitement de la non-livraison et de la censure, puis estimer les effets sur des données contrôlées avant tout apprentissage automatique en production.
