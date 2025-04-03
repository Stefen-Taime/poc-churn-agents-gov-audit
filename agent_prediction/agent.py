import time
import os
import psycopg2
from dotenv import load_dotenv
import joblib # Pour charger le modèle scikit-learn
import pandas as pd
import random

load_dotenv('/app/.env')

# --- Configuration Globale ---
DB_NAME = os.getenv("POSTGRES_DB", "pocdb")
DB_USER = os.getenv("POSTGRES_USER", "pocuser")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "pocpassword")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
MODEL_PATH = os.getenv("MODEL_PATH", "model.pkl") # Chemin vers le modèle dans le conteneur
AGENT_NAME = 'prediction'
PROCESS_INTERVAL_SECONDS = int(os.getenv("PREDICTION_INTERVAL", "45"))
DB_RETRY_DELAY_SECONDS = int(os.getenv("DB_RETRY_DELAY", "10"))
PREDICTION_BATCH_SIZE = int(os.getenv("PREDICTION_BATCH_SIZE", "50")) # Taille du lot pour la prédiction

# --- Fonction Helper pour l'Audit Log --- (Identique aux autres agents)
def log_audit_event(conn, event_type, status='INFO', customer_id=None, details=None):
    """Enregistre un événement dans la table d'audit de manière robuste."""
    if conn is None or conn.closed: print(f"AUDIT LOGGING FAILED (DB disconnected) for event: {AGENT_NAME} - {event_type}"); return
    log_details = str(details) if details is not None else None
    try:
        with conn.cursor() as cur: cur.execute("""INSERT INTO audit_log (agent_name, event_type, status, customer_id, details) VALUES (%s, %s, %s, %s, %s)""", (AGENT_NAME, event_type, status, customer_id, log_details))
        conn.commit()
    except Exception as e: print(f"ERROR [{AGENT_NAME}]: Failed to log audit event ({event_type}): {e}"); conn.rollback()
# --- Fin Fonction Helper ---

def connect_db():
    """Tente de se connecter à la DB avec retries."""
    conn = None; retries = 5
    while retries > 0 and (conn is None or conn.closed):
        try:
            conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT, connect_timeout=5)
            conn.autocommit = False # Gérer les transactions
            print(f"[{AGENT_NAME}] Database connection successful (Host: {DB_HOST}).")
            log_audit_event(conn, 'DB_CONNECT', status='SUCCESS', details=f"Connected to {DB_HOST}")
            return conn
        except psycopg2.OperationalError as e:
            print(f"WARNING [{AGENT_NAME}]: Database connection error: {e}. Retrying in {DB_RETRY_DELAY_SECONDS}s... ({retries-1} retries left)")
            retries -= 1; time.sleep(DB_RETRY_DELAY_SECONDS)
        except Exception as ex:
            print(f"ERROR [{AGENT_NAME}]: Unexpected DB connection error: {ex}. Retrying in {DB_RETRY_DELAY_SECONDS*2}s... ({retries-1} retries left)")
            retries -= 1; time.sleep(DB_RETRY_DELAY_SECONDS * 2)
    print(f"FATAL [{AGENT_NAME}]: Could not connect to the database. Exiting."); exit(1)

def load_model(conn): # Passer conn pour log audit
    """Charge le modèle ML depuis le fichier .pkl."""
    log_audit_event(conn, 'MODEL_LOAD_START', status='INFO', details=f"Attempting to load model from {MODEL_PATH}")
    try:
        if os.path.exists(MODEL_PATH):
            start_time = time.time()
            model = joblib.load(MODEL_PATH)
            duration = time.time() - start_time
            details = f"Model '{os.path.basename(MODEL_PATH)}' loaded successfully in {duration:.4f}s."
            print(f"[{AGENT_NAME}] {details}")
            log_audit_event(conn, 'MODEL_LOAD_END', status='SUCCESS', details=details)
            return model
        else:
            details = f"Model file not found at path: '{MODEL_PATH}'"
            print(f"ERROR [{AGENT_NAME}]: {details}")
            log_audit_event(conn, 'MODEL_LOAD_END', status='FAILURE', details=details)
            return None
    except Exception as e:
        details = f"Failed to load model from '{MODEL_PATH}': {type(e).__name__} - {e}"
        print(f"ERROR [{AGENT_NAME}]: {details}")
        log_audit_event(conn, 'MODEL_LOAD_END', status='ERROR', details=details)
        return None

def predict_churn(conn, model):
    """Prédit le churn pour les clients sans prédiction, par lots."""
    log_audit_event(conn, 'BATCH_START', status='INFO', details=f"Checking for customers needing prediction (batch size: {PREDICTION_BATCH_SIZE}).")
    print(f"\n[{AGENT_NAME}] Checking for customers...")
    customers_to_predict = []
    processed_in_batch = 0

    try:
        with conn.cursor() as cur:
            # Sélectionner les clients sans prédiction, par lot
            cur.execute(
                """
                SELECT c.customer_id, c.last_activity_days, c.complaints_count
                FROM customers c
                LEFT JOIN predictions p ON c.customer_id = p.customer_id
                WHERE p.prediction_id IS NULL
                ORDER BY c.created_at ASC
                LIMIT %s;
                """, (PREDICTION_BATCH_SIZE,)
            )
            customers_to_predict = cur.fetchall()
            log_audit_event(conn, 'DB_FETCH', status='SUCCESS', details=f"Found {len(customers_to_predict)} customers in current batch.")
            print(f"[{AGENT_NAME}] Found {len(customers_to_predict)} customers in this batch.")
    except psycopg2.Error as db_err:
        log_audit_event(conn, 'DB_FETCH', status='FAILURE', details=f"Failed fetching customers: {db_err}")
        print(f"ERROR [{AGENT_NAME}]: DB Error fetching customers: {db_err}")
        conn.rollback()
        return True # Indique erreur DB

    if not customers_to_predict:
        print(f"[{AGENT_NAME}] No new customers found requiring prediction.")
        log_audit_event(conn, 'BATCH_END', status='INFO', details="No customers found for prediction.")
        return False # Pas d'erreur, juste rien à faire

    # Préparer les données pour le modèle
    df = pd.DataFrame(customers_to_predict, columns=['customer_id', 'last_activity_days', 'complaints_count'])
    
    # !!! IMPORTANT: Assurer la compatibilité avec le modèle entraîné
    try:
        # Ajouter la colonne sentiment_numeric qui est attendue par le modèle
        df['sentiment_numeric'] = 0  # Valeur par défaut
        
        # S'assurer que toutes les colonnes attendues sont présentes
        required_features = ['last_activity_days', 'complaints_count', 'sentiment_numeric']
        features = df[required_features]
        
        print(f"   Prepared features for prediction: {required_features}")
    except KeyError as ke:
        details = f"Missing expected feature columns in fetched data: {ke}"
        print(f"ERROR [{AGENT_NAME}]: {details}")
        log_audit_event(conn, 'DATA_PREPARATION', status='ERROR', details=details)
        log_audit_event(conn, 'BATCH_END', status='FAILURE', details="Batch failed due to data preparation error.")
        return True # Erreur de données, attendre correction potentielle

    probabilities = []
    prediction_status = 'FAILURE'
    log_audit_event(conn, 'PREDICTION_START', status='INFO', details=f"Attempting prediction for {len(df)} customers.")
    start_time = time.time()
    prediction_details = "Prediction not attempted."

    if model:
        try:
            # Assurer que le modèle a la méthode predict_proba
            if hasattr(model, 'predict_proba'):
                probabilities_raw = model.predict_proba(features)[:, 1] # Probabilité de la classe 1 (churn)
                probabilities = probabilities_raw.tolist()
                prediction_status = 'SUCCESS'
                prediction_details = f"Successfully predicted probabilities for {len(probabilities)} customers using loaded model."
                print(f"   {prediction_details}")
            else:
                prediction_status = 'ERROR'
                prediction_details = "Loaded model does not have 'predict_proba' method."
                print(f"   ERROR: {prediction_details}")
        except Exception as e:
            prediction_status = 'ERROR'
            prediction_details = f"Error during prediction with loaded model: {type(e).__name__} - {e}."
            print(f"   ERROR: {prediction_details}")
            # Pas de fallback random ici, on considère que la prédiction a échoué
    else:
        prediction_status = 'FAILURE'
        prediction_details = "Model not loaded. Prediction skipped for this batch."
        print(f"   WARNING: {prediction_details}")

    duration = time.time() - start_time
    log_audit_event(conn, 'PREDICTION_END', status=prediction_status, details=f"{prediction_details} Duration: {duration:.4f}s")

    # Insérer les prédictions SEULEMENT si elles ont été générées avec succès
    if prediction_status == 'SUCCESS' and probabilities:
        values_to_insert = list(zip(df['customer_id'].tolist(), probabilities))
        insert_query = """INSERT INTO predictions (customer_id, churn_probability) VALUES (%s, %s) ON CONFLICT (customer_id) DO NOTHING;"""
        try:
            with conn.cursor() as cur:
                cur.executemany(insert_query, values_to_insert)
            conn.commit() # Commit après l'insertion réussie
            processed_in_batch = len(values_to_insert)
            log_audit_event(conn, 'DB_SAVE', status='SUCCESS', details=f"Inserted {processed_in_batch} predictions.")
            print(f"   Inserted {processed_in_batch} predictions.")
        except psycopg2.Error as db_err:
             log_audit_event(conn, 'DB_SAVE', status='FAILURE', details=f"Prediction insert failed: {db_err}")
             print(f"   ERROR: DB Error inserting predictions: {db_err}")
             conn.rollback() # Annuler l'insertion
             log_audit_event(conn, 'BATCH_END', status='FAILURE', details="Batch failed during DB save.")
             return True # Erreur DB

    log_audit_event(conn, 'BATCH_END', status=prediction_status if prediction_status != 'SUCCESS' else 'INFO', details=f"Finished prediction batch. Saved {processed_in_batch} predictions. Final status: {prediction_status}")
    print(f"[{AGENT_NAME}] Finished batch processing.")
    # Retourner False si succès ou si l'erreur ne nécessite pas d'attente prolongée (ex: modèle manquant)
    # Retourner True si une erreur DB critique s'est produite
    return prediction_status == 'ERROR' or prediction_status == 'FAILURE'

# --- Boucle Principale de l'Agent ---
if __name__ == "__main__":
    print(f"[{AGENT_NAME}] Agent starting up...")
    db_conn = connect_db()
    model = load_model(db_conn) # Charger le modèle une fois au démarrage
    if not model:
        print(f"WARNING [{AGENT_NAME}]: Model was not loaded. Agent will not be able to predict using the model.")
        # L'agent continuera mais logguera des échecs de prédiction

    while True:
        error_occurred = False
        try:
            if db_conn is None or db_conn.closed:
                print(f"WARNING [{AGENT_NAME}]: Database connection found closed. Reconnecting...")
                log_audit_event(db_conn, 'DB_CONNECT', status='WARNING', details='Connection lost, attempting reconnect.')
                db_conn = connect_db()
                # Recharger le modèle si la connexion DB a été perdue? Peut-être pas nécessaire si le modèle est en mémoire.
                # model = load_model(db_conn) # Décommenter si le chargement dépend de la connexion

            error_occurred = predict_churn(db_conn, model)

        except psycopg2.InterfaceError as ie:
             print(f"ERROR [{AGENT_NAME}]: Database InterfaceError: {ie}. Attempting to reconnect...")
             log_audit_event(db_conn, 'DB_CONNECT', status='ERROR', details=f'InterfaceError: {ie}')
             if db_conn and not db_conn.closed:
                 try: db_conn.close()
                 except Exception: pass
             db_conn = connect_db()
             error_occurred = True

        except Exception as e:
             print(f"FATAL [{AGENT_NAME}]: An unexpected error occurred in main loop: {e}")
             log_audit_event(db_conn, 'UNEXPECTED_ERROR', status='ERROR', details=f"Main loop error: {type(e).__name__} - {e}")
             error_occurred = True

        # Attente avant le prochain cycle
        current_wait_time = DB_RETRY_DELAY_SECONDS * 2 if error_occurred else PROCESS_INTERVAL_SECONDS
        print(f"[{AGENT_NAME}] Waiting for {current_wait_time} seconds before next cycle...")
        time.sleep(current_wait_time)