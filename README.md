# POC : Prédiction de Churn et Actions de Rétention avec Agents IA (Docker & Groq) - Démo Gouvernance & Audit

Ce projet est un Proof of Concept (POC) démontrant comment une architecture basée sur des agents IA, orchestrée avec Docker Compose, peut être utilisée pour prédire le churn client et générer des actions de rétention personnalisées en utilisant un LLM (via l'API Groq).

Un accent particulier est mis sur la **démonstration des principes de gouvernance des données**, incluant une **piste d'audit**, même dans le contexte d'un POC utilisant des données synthétiques.

## Architecture

Le système est composé de plusieurs services conteneurisés :

1.  **`db` (PostgreSQL) :** Stocke les données clients (synthétiques), les analyses de feedback, les prédictions de churn, les actions recommandées, et une **table `audit_log`** dédiée.
2.  **`agent_nlp` :**
    *   Lit les feedbacks clients depuis la base de données.
    *   **Logue les étapes clés** dans `audit_log`.
    *   **Vérifie le consentement** client (logué).
    *   **Anonymise** le texte du feedback (simulé et logué).
    *   Appelle l'API Groq (appel logué).
    *   Stocke les résultats de l'analyse (sauvegarde loguée).
3.  **`agent_prediction` :**
    *   Charge un modèle ML (chargement logué).
    *   Lit les caractéristiques clients.
    *   Prédit la probabilité de churn (prédiction loguée).
    *   Stocke les prédictions (sauvegarde loguée).
4.  **`agent_segmentation_action` :**
    *   Lit les prédictions et analyses.
    *   Détermine un segment de risque.
    *   Appelle l'API Groq pour générer une action (appel logué).
    *   Stocke le segment et l'action (sauvegarde loguée).
5.  **`ui_dashboard` (Streamlit) :**
    *   Fournit une interface web pour visualiser les données, analyses, prédictions, actions, et **les logs d'audit**.

## Démonstration de la Gouvernance des Données (dans le POC)

Ce POC intègre plusieurs éléments pour démontrer comment la gouvernance serait gérée en production :

1.  **Données Synthétiques Uniquement :** Aucune donnée client réelle n'est utilisée.
2.  **Vérification du Consentement :** L'`agent_nlp` vérifie et logue le statut du consentement.
3.  **Anonymisation Simulée :** L'`agent_nlp` applique et logue l'étape d'anonymisation avant l'appel externe.
4.  **Isolation des Appels Externes :** Seuls les agents désignés communiquent avec l'API externe.
5.  **Logging et Auditabilité :**
    *   Une table **`audit_log`** dédiée enregistre les événements critiques (vérifications, appels API, sauvegardes BDD, erreurs).
    *   Chaque agent utilise une fonction helper pour écrire dans cette table, fournissant une piste d'audit centralisée.
    *   Ces logs sont visibles dans le dashboard pour une transparence accrue.
6.  **Gestion Sécurisée des Secrets (Basique) :** Clé API via `.env` (à protéger et remplacer par Vault en prod).
7.  **Transition vers la Production :** Rappel que Groq serait remplacé par un LLM interne/privé en production. En production, l'audit pourrait être géré par un agent dédié et un message queue pour plus de résilience et de découplage.

## Prérequis

*   Docker
*   Docker Compose
*   Une clé API Groq (obtenue sur [console.groq.com](https://console.groq.com/))
*   Python (pour créer le modèle `model.pkl` initialement)
*   Bibliothèques Python locales: `scikit-learn`, `pandas`, `joblib` (ou `pickle`) pour créer le modèle.

## Installation et Lancement

1.  **Cloner le dépôt ou créer la structure de fichiers.**
2.  **Créer le fichier `.env`** à la racine et ajoutez vos identifiants de base de données (peuvent rester ceux par défaut) et votre clé API Groq :
    ```env
    POSTGRES_USER=pocuser
    POSTGRES_PASSWORD=pocpassword
    POSTGRES_DB=pocdb
    GROQ_API_KEY=gsk_VOTRE_CLE_API_GROQ_ICI
    ```
3.  **Créer le modèle `model.pkl` :**
    *   Exécutez le script Python `create_model.py` fourni pour générer un modèle basique de prédiction de churn.
    *   Le modèle sera sauvegardé dans le dossier `agent_prediction/` sous le nom `model.pkl`.
4.  **Construire et Lancer les Conteneurs :** Depuis le dossier racine `poc-churn-agents-gov-audit/`
    ```bash
    docker-compose up --build -d
    ```
    *   Le `-d` lance les conteneurs en arrière-plan. Enlevez-le pour voir tous les logs en direct.
5.  **Accéder au Dashboard :** Ouvrez votre navigateur et allez à `http://localhost:8501`.
6.  **Observer les Logs Docker :** Pour voir l'activité brute des agents :
    ```bash
    docker-compose logs -f agent_nlp
    docker-compose logs -f agent_prediction
    docker-compose logs -f agent_segmentation_action
    ```
7.  **Consulter l'Audit Log :** Via la section dédiée ("Audit Log") dans le dashboard Streamlit.
8.  **Arrêter les Conteneurs :**
    ```bash
    docker-compose down
    ```

## Structure du Projet

```
poc-churn-agents-gov-audit/
├── docker-compose.yml
├── .env
├── README.md
├── create_model.py
│
├── data_source/
│   └── init.sql
│
├── agent_nlp/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── agent.py
│
├── agent_prediction/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── model.pkl            # (Créé par create_model.py)
│   └── agent.py
│
├── agent_segmentation_action/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── agent.py
│
└── ui_dashboard/
    ├── Dockerfile
    ├── requirements.txt
    └── app.py
```

## Fonctionnement des Agents

### Agent NLP
Analyse les feedbacks clients en utilisant l'API Groq pour extraire le sentiment, les sujets clés et un résumé. Vérifie le consentement et anonymise les données avant tout appel externe.

### Agent Prediction
Utilise un modèle ML simple pour prédire la probabilité de churn de chaque client en fonction de caractéristiques comme le nombre de jours depuis la dernière activité et le nombre de plaintes.

### Agent Segmentation & Action
Segmente les clients en catégories de risque (Élevé, Moyen, Faible) et génère des actions de rétention personnalisées via l'API Groq en tenant compte du segment de risque et de l'analyse du feedback.

### Dashboard UI
Interface utilisateur Streamlit permettant de visualiser toutes les données et les logs d'audit, avec des filtres pour faciliter l'exploration.

## Notes Importantes

- Ce POC est conçu pour démontrer des principes d'architecture et de gouvernance, pas pour être déployé en production tel quel.
- Les données sont entièrement synthétiques et générées à des fins de démonstration.
- En production, l'API Groq serait remplacée par un LLM interne ou privé avec des contrôles de sécurité supplémentaires.
- La gestion des secrets (.env) est simplifiée pour ce POC et devrait être renforcée en production.

## Licence

Ce projet est fourni à titre d'exemple et peut être utilisé librement comme base pour vos propres POCs ou projets.
# poc-churn-agents-gov-audit
