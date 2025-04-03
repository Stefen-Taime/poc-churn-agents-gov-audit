import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
import joblib
import os
import psycopg2
from sqlalchemy import create_engine
import warnings
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

warnings.filterwarnings('ignore')

def load_data_from_db():
    """
    Fonction pour charger les données depuis la base PostgreSQL.
    Dans un environnement réel, utilisez les variables d'environnement pour les identifiants.
    """
    try:
        # Utilisation des variables d'environnement pour la connexion
        postgres_user = os.environ.get("POSTGRES_USER", "pocuser")
        postgres_password = os.environ.get("POSTGRES_PASSWORD", "pocpassword")
        postgres_db = os.environ.get("POSTGRES_DB", "pocdb")
        postgres_host = os.environ.get("POSTGRES_HOST", "localhost")  # Généralement 'db' dans un environnement Docker
        
        conn_string = f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}:5432/{postgres_db}"
        engine = create_engine(conn_string)
        
        # Requête SQL qui joint les tables pertinentes
        query = """
        SELECT 
            c.customer_id,
            c.last_activity_days,
            c.complaints_count,
            fa.sentiment,
            -- Ajoutez ici une définition de "churned" basée sur vos données
            -- Par exemple, considérons qu'un client est churned si:
            CASE 
                WHEN c.last_activity_days > 90 OR c.complaints_count >= 3 THEN 1
                ELSE 0
            END as churned
        FROM 
            customers c
        LEFT JOIN 
            feedback_analysis fa ON c.customer_id = fa.customer_id
        WHERE 
            c.consent_given = TRUE  -- Respecte la gouvernance des données
        """
        
        # Charger les données dans un DataFrame
        df = pd.read_sql(query, engine)
        
        # Transformer la colonne sentiment en variables numériques
        df['sentiment_numeric'] = df['sentiment'].map({
            'Positive': 1,
            'Neutral': 0,
            'Negative': -1,
            'Mixed': 0
        }).fillna(0)  # Valeur par défaut si sentiment est NULL
        
        print(f"Données chargées: {len(df)} enregistrements")
        return df
        
    except Exception as e:
        print(f"Erreur lors du chargement des données: {e}")
        # Fallback: utiliser des données synthétiques comme dans votre exemple original
        print("Utilisation de données factices de fallback")
        return create_fallback_data()

def create_fallback_data():
    """Créer des données factices en cas d'échec de connexion à la BD"""
    # Données d'entraînement factices étendues
    data = {
        'customer_id': [1, 2, 3, 4, 5, 6, 7],
        'last_activity_days': [5, 95, 30, 150, 10, 200, 60],
        'complaints_count': [0, 3, 1, 5, 0, 2, 0],
        'sentiment_numeric': [1, -1, 0, -1, 0, -1, 1],
        'churned': [0, 1, 0, 1, 0, 1, 0]  # Cible
    }
    return pd.DataFrame(data)

def train_and_evaluate_model(df):
    """Entraîne et évalue le modèle"""
    # Préparation des données
    features = ['last_activity_days', 'complaints_count', 'sentiment_numeric']
    X = df[features]
    y = df['churned']
    
    # Si nous avons suffisamment de données, faire un split train/test
    if len(df) > 10:
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42)
        
        # Entraînement
        model = LogisticRegression(class_weight='balanced', max_iter=1000)
        model.fit(X_train, y_train)
        
        # Évaluation
        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        print(f"Précision du modèle: {accuracy:.2f}")
        print("\nRapport de classification:")
        print(classification_report(y_test, y_pred))
        print("\nMatrice de confusion:")
        print(confusion_matrix(y_test, y_pred))
        
        # Importance des variables
        coef = pd.DataFrame(
            zip(features, model.coef_[0]),
            columns=['Feature', 'Coefficient']
        ).sort_values('Coefficient', ascending=False)
        print("\nImportance des variables:")
        print(coef)
        
        return model
    else:
        # Si trop peu de données pour un split, utiliser validation croisée
        model = LogisticRegression(class_weight='balanced', max_iter=1000)
        cv_scores = cross_val_score(model, X, y, cv=3)
        print(f"Scores de validation croisée: {cv_scores}")
        print(f"Score moyen: {np.mean(cv_scores):.2f}")
        
        # Entraînement final sur toutes les données
        model.fit(X, y)
        return model

def save_model(model, version='v1'):
    """Sauvegarde le modèle avec versionnage"""
    output_dir = 'agent_prediction/models'
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # Ajouter un timestamp pour le versionnage
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    model_path = os.path.join(output_dir, f'churn_model_{version}_{timestamp}.pkl')
    
    joblib.dump(model, model_path)
    
    # Créer aussi un lien symbolique vers la dernière version
    latest_path = os.path.join(output_dir, 'churn_model_latest.pkl')
    if os.path.exists(latest_path):
        os.remove(latest_path)
    joblib.dump(model, latest_path)
    
    print(f"Modèle sauvegardé: {model_path}")
    print(f"Modèle 'latest' mis à jour: {latest_path}")
    
    return model_path

def log_to_audit(agent_name, event_type, status="SUCCESS", customer_id=None, details=None):
    """
    Fonction pour écrire dans la table d'audit pour la gouvernance
    """
    try:
        # Connexion à la base de données
        postgres_user = os.environ.get("POSTGRES_USER", "pocuser")
        postgres_password = os.environ.get("POSTGRES_PASSWORD", "pocpassword")
        postgres_db = os.environ.get("POSTGRES_DB", "pocdb")
        postgres_host = os.environ.get("POSTGRES_HOST", "db")
        
        conn = psycopg2.connect(
            host=postgres_host,
            database=postgres_db,
            user=postgres_user,
            password=postgres_password
        )
        
        # Créer un curseur
        cursor = conn.cursor()
        
        # Insérer le log dans la table audit_log
        cursor.execute(
            """
            INSERT INTO audit_log (agent_name, event_type, status, customer_id, details)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (agent_name, event_type, status, customer_id, details)
        )
        
        # Commit et fermeture
        conn.commit()
        cursor.close()
        conn.close()
        
        print(f"AUDIT: {agent_name} | {event_type} | {status} | Client: {customer_id} | {details}")
        
    except Exception as e:
        print(f"ERREUR D'AUDIT: Impossible d'écrire dans la table audit_log: {e}")
        print(f"AUDIT (non enregistré): {agent_name} | {event_type} | {status} | Client: {customer_id} | {details}")

def main():
    try:
        log_to_audit("prediction", "MODEL_TRAINING_START", "INFO", None, "Démarrage de l'entraînement du modèle")
        
        # Chargement des données
        df = load_data_from_db()
        
        # Entraînement et évaluation
        model = train_and_evaluate_model(df)
        
        # Sauvegarde
        model_path = save_model(model)
        
        log_to_audit("prediction", "MODEL_TRAINING_END", "SUCCESS", None, 
                    f"Modèle entraîné et sauvegardé: {model_path}")
        
        # Tester une prédiction
        first_client = df.iloc[0]
        features = ['last_activity_days', 'complaints_count', 'sentiment_numeric']
        X_sample = first_client[features].values.reshape(1, -1)
        
        prob = model.predict_proba(X_sample)[0, 1]  # Probabilité de churn
        print(f"\nTest de prédiction pour le client {first_client['customer_id']}:")
        print(f"Caractéristiques: {dict(zip(features, X_sample[0]))}")
        print(f"Probabilité de churn: {prob:.2f}")
        
        return {
            "status": "success",
            "model_path": model_path,
            "accuracy": model.score(df[features], df['churned'])
        }
    
    except Exception as e:
        log_to_audit("prediction", "MODEL_TRAINING_ERROR", "ERROR", None, f"Erreur: {str(e)}")
        print(f"Erreur lors de l'entraînement: {e}")
        return {
            "status": "error",
            "error": str(e)
        }

if __name__ == "__main__":
    main()