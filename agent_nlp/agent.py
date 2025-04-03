import time
import os
import psycopg2
from dotenv import load_dotenv
from groq import Groq, RateLimitError, APIError

# Charger les variables d'environnement depuis .env
load_dotenv('/app/.env')

# --- Configuration Globale ---
DB_NAME = os.getenv("POSTGRES_DB", "pocdb")
DB_USER = os.getenv("POSTGRES_USER", "pocuser")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "pocpassword")
DB_HOST = os.getenv("DB_HOST", "db")
DB_PORT = os.getenv("DB_PORT", "5432")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama3-8b-8192")
AGENT_NAME = 'action'
PROCESS_INTERVAL_SECONDS = int(os.getenv("ACTION_INTERVAL", "60"))
API_RETRY_DELAY_SECONDS = int(os.getenv("API_RETRY_DELAY", "60"))
DB_RETRY_DELAY_SECONDS = int(os.getenv("DB_RETRY_DELAY", "10"))
ACTION_BATCH_SIZE = int(os.getenv("ACTION_BATCH_SIZE", "10")) # Traiter par petits lots

# Seuils de risque (ajustables)
HIGH_RISK_THRESHOLD = float(os.getenv("HIGH_RISK_THRESHOLD", "0.70"))
MEDIUM_RISK_THRESHOLD = float(os.getenv("MEDIUM_RISK_THRESHOLD", "0.35"))

# Vérification critique de la clé API au démarrage
if not GROQ_API_KEY:
    print(f"FATAL [{AGENT_NAME}]: GROQ_API_KEY not found.")
    exit(1) # Arrêter le conteneur si la clé manque

# Initialisation globale du client Groq
try:
    client = Groq(api_key=GROQ_API_KEY)
    print(f"[{AGENT_NAME}] Groq client initialized.")
except Exception as e:
    print(f"FATAL [{AGENT_NAME}]: Failed to initialize Groq client: {e}.")
    exit(1)

# --- Fonction Helper pour l'Audit Log --- (Identique aux autres agents)
def log_audit_event(conn, event_type, status='INFO', customer_id=None, details=None):
    """Enregistre un événement dans la table d'audit de manière robuste."""
    if conn is None or conn.closed:
        print(f"AUDIT LOGGING FAILED (DB disconnected) for event: {AGENT_NAME} - {event_type}")
        return
    log_details = str(details) if details is not None else None # Assurer que details est une chaîne ou None
    try:
        # Utiliser un nouveau curseur pour l'audit pour éviter les interférences
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO audit_log (agent_name, event_type, status, customer_id, details)
                   VALUES (%s, %s, %s, %s, %s)""",
                (AGENT_NAME, event_type, status, customer_id, log_details)
            )
        # Important: Commit après chaque log d'audit pour le rendre persistant immédiatement
        conn.commit()
    except Exception as e:
        print(f"ERROR [{AGENT_NAME}]: Failed to log audit event ({event_type}): {e}")
        # Essayer d'annuler la transaction d'audit qui a échoué
        try:
            conn.rollback()
        except Exception as rollback_err:
            print(f"ERROR [{AGENT_NAME}]: Failed to rollback audit transaction: {rollback_err}")
# --- Fin Fonction Helper ---

def connect_db():
    """Tente de se connecter à la DB avec retries."""
    conn = None
    retries = 5
    while retries > 0 and (conn is None or conn.closed):
        try:
            conn = psycopg2.connect(
                dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT,
                connect_timeout=5 # Timeout pour l'établissement de la connexion
            )
            conn.autocommit = False # Désactiver l'autocommit pour gérer les transactions manuellement
            print(f"[{AGENT_NAME}] Database connection successful (Host: {DB_HOST}).")
            log_audit_event(conn, 'DB_CONNECT', status='SUCCESS', details=f"Connected to {DB_HOST}")
            return conn # Sortir de la boucle si succès
        except psycopg2.OperationalError as e:
            print(f"WARNING [{AGENT_NAME}]: Database connection error: {e}. Retrying in {DB_RETRY_DELAY_SECONDS}s... ({retries-1} retries left)")
            retries -= 1
            time.sleep(DB_RETRY_DELAY_SECONDS)
        except Exception as ex:
            print(f"ERROR [{AGENT_NAME}]: Unexpected DB connection error: {ex}. Retrying in {DB_RETRY_DELAY_SECONDS*2}s... ({retries-1} retries left)")
            retries -= 1
            time.sleep(DB_RETRY_DELAY_SECONDS * 2)

    print(f"FATAL [{AGENT_NAME}]: Could not connect to the database. Exiting.")
    exit(1) # Arrêter si la connexion échoue après plusieurs tentatives

def call_groq_generate_action(conn, customer_id, probability, risk_segment, feedback_summary, sentiment, topics):
    """Appelle Groq pour générer une recommandation d'action."""
    prompt = f"""
    Act as an expert customer retention strategist for a retail bank.
    A customer (ID: {customer_id}) needs a retention action recommendation based on the following data:

    *   Churn Risk Probability: {probability:.2f} (Categorized as: {risk_segment})
    *   Analysis of recent feedback (if available):
        *   Summary: {feedback_summary if feedback_summary else 'N/A'}
        *   Overall Sentiment: {sentiment if sentiment else 'N/A'}
        *   Key Topics Mentioned: {topics if topics else 'N/A'}

    Based ONLY on this information, provide ONE SINGLE, concise, and actionable next step for a bank employee.
    - If risk is High and sentiment Negative, suggest an urgent and specific intervention addressing the topics.
    - If risk is Medium, suggest a targeted proactive measure, possibly referencing feedback topics.
    - If risk is Low, suggest standard monitoring or a simple positive reinforcement if feedback was good.
    - Be specific where possible (e.g., "offer waiver for [topic]", "explain feature related to [topic]").
    - Do not invent information not present above.

    Respond with only the suggested action text, starting directly with the action verb. Example: "Schedule a call to discuss fee concerns and offer a one-time waiver." or "Monitor account activity; send standard loyalty email next cycle."

    Suggested Action:
    """
    log_audit_event(conn, 'GROQ_CALL_START', status='INFO', customer_id=customer_id, details=f"Generate action. Risk: {risk_segment}, Prob: {probability:.2f}, Model: {GROQ_MODEL}")
    start_time = time.time()
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.4, # Un peu directif
            max_tokens=120,
            timeout=25.0 # Timeout pour l'appel API
        )
        action = chat_completion.choices[0].message.content.strip()
        # Nettoyer les préfixes potentiels
        if action.startswith("Suggested Action:"): action = action.replace("Suggested Action:", "").strip()
        if not action: action = "No specific action suggested by LLM." # Default si réponse vide

        duration = time.time() - start_time
        log_audit_event(conn, 'GROQ_CALL_END', status='SUCCESS', customer_id=customer_id, details=f"Generated: '{action[:60]}...'. Duration: {duration:.2f}s")
        print(f"   Groq generated action in {duration:.2f}s: {action[:80]}...")
        return action

    except RateLimitError as e:
        duration = time.time() - start_time
        log_audit_event(conn, 'GROQ_CALL_END', status='FAILURE', customer_id=customer_id, details=f"Rate Limit Error after {duration:.2f}s: {e}")
        print(f"WARNING [{AGENT_NAME}]: Groq Rate Limit Reached for customer {customer_id}.")
        return None # Indique condition pour retry/attente
    except APIError as e:
        duration = time.time() - start_time
        log_audit_event(conn, 'GROQ_CALL_END', status='ERROR', customer_id=customer_id, details=f"API Error after {duration:.2f}s: {e}")
        print(f"ERROR [{AGENT_NAME}]: Groq API Error for customer {customer_id}: {e}")
        return "API_ERROR" # Indique erreur permanente pour cet essai
    except Exception as e:
        duration = time.time() - start_time
        error_type = type(e).__name__
        log_audit_event(conn, 'GROQ_CALL_END', status='ERROR', customer_id=customer_id, details=f"Unexpected Groq Error ({error_type}) after {duration:.2f}s: {e}")
        print(f"ERROR [{AGENT_NAME}]: Unexpected error during Groq call for customer {customer_id}: {e}")
        return "UNEXPECTED_ERROR"

def process_predictions_for_actions(conn):
    """Traite les prédictions qui n'ont pas encore d'action recommandée."""
    log_audit_event(conn, 'BATCH_START', status='INFO', details=f"Checking for predictions needing actions (batch size: {ACTION_BATCH_SIZE}).")
    print(f"\n[{AGENT_NAME}] Checking for predictions...")
    predictions_to_process = []
    processed_in_batch = 0
    api_related_failure = False

    try:
        with conn.cursor() as cur:
            # Sélectionner prédictions sans action, joindre analyse NLP, traiter par lots
            cur.execute(
                """
                SELECT
                    p.customer_id, p.churn_probability,
                    fa.feedback_summary, fa.sentiment, fa.key_topics
                FROM predictions p
                LEFT JOIN feedback_analysis fa ON p.customer_id = fa.customer_id
                LEFT JOIN actions a ON p.customer_id = a.customer_id
                WHERE a.action_id IS NULL
                ORDER BY p.predicted_at ASC -- Traiter les plus anciennes prédictions d'abord
                LIMIT %s;
                """, (ACTION_BATCH_SIZE,)
            )
            predictions_to_process = cur.fetchall()
            log_audit_event(conn, 'DB_FETCH', status='SUCCESS', details=f"Found {len(predictions_to_process)} predictions in current batch.")
            print(f"[{AGENT_NAME}] Found {len(predictions_to_process)} predictions in this batch.")
    except psycopg2.Error as db_err:
        log_audit_event(conn, 'DB_FETCH', status='FAILURE', details=f"Failed fetching predictions: {db_err}")
        print(f"ERROR [{AGENT_NAME}]: DB Error fetching predictions: {db_err}")
        conn.rollback()
        return True # Erreur DB, attendre

    if not predictions_to_process:
        print(f"[{AGENT_NAME}] No new predictions found needing action.")
        log_audit_event(conn, 'BATCH_END', status='INFO', details="No predictions found to process.")
        return False # OK, rien à faire

    # Traitement du lot
    actions_to_insert = []
    for row in predictions_to_process:
        customer_id, probability, summary, sentiment, topics = row
        probability = probability or 0.0 # Default si NULL
        log_audit_event(conn, 'PROCESSING_START', status='INFO', customer_id=customer_id, details=f"Processing prediction. Prob={probability:.2f}")
        print(f"\nProcessing Customer ID: {customer_id} (Prob: {probability:.2f})")

        # Déterminer le segment
        risk_segment = "Low Risk"
        if probability >= HIGH_RISK_THRESHOLD: risk_segment = "High Risk"
        elif probability >= MEDIUM_RISK_THRESHOLD: risk_segment = "Medium Risk"
        log_audit_event(conn, 'SEGMENTATION', status='SUCCESS', customer_id=customer_id, details=f"Segment determined: {risk_segment}")
        print(f"   Segment: {risk_segment}")

        # Appel Groq pour l'action
        recommended_action = call_groq_generate_action(conn, customer_id, probability, risk_segment, summary, sentiment, topics)

        if recommended_action is None: # Indique Rate Limit
            print(f"   API Rate Limit hit. Stopping current batch processing.")
            api_related_failure = True
            log_audit_event(conn, 'PROCESSING_END', status='INTERRUPTED', customer_id=customer_id, details="Batch stopped due to API rate limit.")
            break # Arrêter le lot
        elif "ERROR" in recommended_action: # Indique erreur API ou autre
             print(f"   API or unexpected error during action generation. Skipping save for this customer.")
             api_related_failure = True # Considérer comme failure pour l'attente
             log_audit_event(conn, 'PROCESSING_END', status='FAILURE', customer_id=customer_id, details=f"Action generation failed: {recommended_action}")
             continue # Passer au suivant (erreur déjà loggée par call_groq)
        else:
            # Action générée avec succès
            actions_to_insert.append((customer_id, risk_segment, recommended_action))
            log_audit_event(conn, 'ACTION_GENERATED', status='SUCCESS', customer_id=customer_id, details=f"Action: {recommended_action[:60]}...")
            print(f"   Action generated: {recommended_action[:80]}...")
            processed_in_batch += 1
            # Pas de sleep ici pour l'instant, on le mettra après le commit groupé si besoin
            log_audit_event(conn, 'PROCESSING_END', status='SUCCESS', customer_id=customer_id)


    # Insérer les actions générées pour ce lot
    if actions_to_insert:
        insert_query = """INSERT INTO actions (customer_id, segment, recommended_action) VALUES (%s, %s, %s) ON CONFLICT (customer_id) DO NOTHING;"""
        try:
            with conn.cursor() as cur:
                cur.executemany(insert_query, actions_to_insert)
            conn.commit() # Commit après l'insertion réussie du lot
            log_audit_event(conn, 'DB_SAVE', status='SUCCESS', details=f"Inserted {len(actions_to_insert)} actions.")
            print(f"\n[{AGENT_NAME}] Inserted {len(actions_to_insert)} new actions.")
            # Petite pause après un batch réussi avec appels API
            if not api_related_failure: # Ne pas pauser si on s'est arrêté pour rate limit
                 time.sleep(1.0)
        except psycopg2.Error as db_err:
             log_audit_event(conn, 'DB_SAVE', status='FAILURE', details=f"Action insert failed for batch: {db_err}")
             print(f"   ERROR [{AGENT_NAME}]: DB Error inserting actions batch: {db_err}")
             conn.rollback()
             log_audit_event(conn, 'BATCH_END', status='FAILURE', details="Batch failed during DB save.")
             return True # Erreur DB

    log_audit_event(conn, 'BATCH_END', status='INFO' if not api_related_failure else 'INTERRUPTED', details=f"Finished action batch. Generated/Saved {len(actions_to_insert)} actions. API failure encountered: {api_related_failure}")
    print(f"[{AGENT_NAME}] Finished batch processing.")
    return api_related_failure

# --- Boucle Principale de l'Agent ---
if __name__ == "__main__":
    print(f"[{AGENT_NAME}] Agent starting up...")
    db_conn = connect_db()

    while True:
        error_occurred = False # Inclut rate limit pour l'attente
        try:
            if db_conn is None or db_conn.closed:
                print(f"WARNING [{AGENT_NAME}]: Database connection found closed. Reconnecting...")
                log_audit_event(db_conn, 'DB_CONNECT', status='WARNING', details='Connection lost, attempting reconnect.')
                db_conn = connect_db()

            error_occurred = process_predictions_for_actions(db_conn)

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

        # Attente
        current_wait_time = API_RETRY_DELAY_SECONDS if error_occurred else PROCESS_INTERVAL_SECONDS
        print(f"[{AGENT_NAME}] Waiting for {current_wait_time} seconds before next cycle...")
        time.sleep(current_wait_time)