import time
import os
import psycopg2
from dotenv import load_dotenv

# Désactiver explicitement tous les proxies au niveau du système AVANT d'importer Groq
for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'no_proxy', 'NO_PROXY']:
    if proxy_var in os.environ:
        os.environ[proxy_var] = ""

# Maintenant on peut importer Groq en toute sécurité
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
AGENT_NAME = 'nlp'
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

# Initialisation globale du client Groq - VERSION SIMPLIFIÉE SANS RESTAURATION DE PROXY
try:
    # S'assurer une dernière fois que les proxies sont désactivés
    for proxy_var in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 'no_proxy', 'NO_PROXY']:
        if proxy_var in os.environ:
            os.environ[proxy_var] = ""
    
    # Initialiser le client sans l'influence des proxies
    client = Groq(api_key=GROQ_API_KEY)
    print(f"[{AGENT_NAME}] Groq client initialized successfully.")
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

def analyze_feedback(conn, customer_id, feedback_text):
    """Appelle Groq pour analyser un feedback client."""
    if not feedback_text or feedback_text.strip() == '':
        return "No feedback provided", "Neutral", "No topics identified"
    
    prompt = f"""
    Act as an expert customer feedback analyzer for a retail bank.
    
    Analyze the following customer feedback (Customer ID: {customer_id}):
    
    "{feedback_text}"
    
    Provide your analysis in the following format:
    
    SUMMARY: [1-2 sentence summary of the key points in the feedback]
    SENTIMENT: [Single word: Positive, Negative, or Neutral]
    TOPICS: [Comma-separated list of key topics mentioned, max 5 topics]
    
    Keep your analysis factual and based only on what is explicitly mentioned in the feedback.
    Do not make assumptions or add information not present in the text.
    """
    
    log_audit_event(conn, 'GROQ_CALL_START', status='INFO', customer_id=customer_id, 
                   details=f"Analyzing feedback. Length: {len(feedback_text)}, Model: {GROQ_MODEL}")
    start_time = time.time()
    
    try:
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=GROQ_MODEL,
            temperature=0.1,  # Réponse factuelle
            max_tokens=200,
            timeout=25.0  # Timeout pour l'appel API
        )
        
        analysis = chat_completion.choices[0].message.content.strip()
        duration = time.time() - start_time
        
        # Extraire les parties de l'analyse
        summary = "No summary generated"
        sentiment = "Neutral"
        topics = "No topics identified"
        
        for line in analysis.split('\n'):
            if line.startswith('SUMMARY:'):
                summary = line.replace('SUMMARY:', '').strip()
            elif line.startswith('SENTIMENT:'):
                sentiment = line.replace('SENTIMENT:', '').strip()
            elif line.startswith('TOPICS:'):
                topics = line.replace('TOPICS:', '').strip()
        
        log_audit_event(conn, 'GROQ_CALL_END', status='SUCCESS', customer_id=customer_id, 
                       details=f"Analysis completed. Sentiment: {sentiment}. Duration: {duration:.2f}s")
        print(f"   Groq analyzed feedback in {duration:.2f}s. Sentiment: {sentiment}")
        
        return summary, sentiment, topics
        
    except RateLimitError as e:
        duration = time.time() - start_time
        log_audit_event(conn, 'GROQ_CALL_END', status='FAILURE', customer_id=customer_id, 
                       details=f"Rate Limit Error after {duration:.2f}s: {e}")
        print(f"WARNING [{AGENT_NAME}]: Groq Rate Limit Reached for customer {customer_id}.")
        return None, None, None  # Indique rate limit
        
    except APIError as e:
        duration = time.time() - start_time
        log_audit_event(conn, 'GROQ_CALL_END', status='ERROR', customer_id=customer_id, 
                       details=f"API Error after {duration:.2f}s: {e}")
        print(f"ERROR [{AGENT_NAME}]: Groq API Error for customer {customer_id}: {e}")
        return "API_ERROR", "API_ERROR", "API_ERROR"
        
    except Exception as e:
        duration = time.time() - start_time
        error_type = type(e).__name__
        log_audit_event(conn, 'GROQ_CALL_END', status='ERROR', customer_id=customer_id, 
                       details=f"Unexpected Groq Error ({error_type}) after {duration:.2f}s: {e}")
        print(f"ERROR [{AGENT_NAME}]: Unexpected error during Groq call for customer {customer_id}: {e}")
        return "UNEXPECTED_ERROR", "UNEXPECTED_ERROR", "UNEXPECTED_ERROR"

def process_feedback_for_analysis(conn):
    """Traite les feedbacks clients qui n'ont pas encore été analysés."""
    log_audit_event(conn, 'BATCH_START', status='INFO', 
                   details=f"Checking for feedback needing analysis (batch size: {ACTION_BATCH_SIZE}).")
    print(f"\n[{AGENT_NAME}] Checking for customer feedback...")
    feedback_to_process = []
    processed_in_batch = 0
    api_related_failure = False

    try:
        with conn.cursor() as cur:
            # Sélectionner feedbacks sans analyse, traiter par lots
            cur.execute(
                """
                SELECT f.customer_id, f.feedback_text
                FROM customer_feedback f
                LEFT JOIN feedback_analysis fa ON f.customer_id = fa.customer_id
                WHERE fa.analysis_id IS NULL AND f.feedback_text IS NOT NULL AND f.feedback_text != ''
                ORDER BY f.submitted_at ASC -- Traiter les plus anciens feedbacks d'abord
                LIMIT %s;
                """, (ACTION_BATCH_SIZE,)
            )
            feedback_to_process = cur.fetchall()
            log_audit_event(conn, 'DB_FETCH', status='SUCCESS', 
                           details=f"Found {len(feedback_to_process)} feedback items in current batch.")
            print(f"[{AGENT_NAME}] Found {len(feedback_to_process)} feedback items in this batch.")
    except psycopg2.Error as db_err:
        log_audit_event(conn, 'DB_FETCH', status='FAILURE', details=f"Failed fetching feedback: {db_err}")
        print(f"ERROR [{AGENT_NAME}]: DB Error fetching feedback: {db_err}")
        conn.rollback()
        return True  # Erreur DB, attendre

    if not feedback_to_process:
        print(f"[{AGENT_NAME}] No new feedback found needing analysis.")
        log_audit_event(conn, 'BATCH_END', status='INFO', details="No feedback found to process.")
        return False  # OK, rien à faire

    # Traitement du lot
    analyses_to_insert = []
    for row in feedback_to_process:
        customer_id, feedback_text = row
        log_audit_event(conn, 'PROCESSING_START', status='INFO', customer_id=customer_id, 
                       details=f"Processing feedback. Length={len(feedback_text)}")
        print(f"\nProcessing Customer ID: {customer_id} (Feedback length: {len(feedback_text)})")

        # Appel Groq pour l'analyse
        summary, sentiment, topics = analyze_feedback(conn, customer_id, feedback_text)

        if summary is None:  # Indique Rate Limit
            print(f"   API Rate Limit hit. Stopping current batch processing.")
            api_related_failure = True
            log_audit_event(conn, 'PROCESSING_END', status='INTERRUPTED', customer_id=customer_id, 
                           details="Batch stopped due to API rate limit.")
            break  # Arrêter le lot
        elif "ERROR" in summary:  # Indique erreur API ou autre
            print(f"   API or unexpected error during feedback analysis. Skipping save for this customer.")
            api_related_failure = True  # Considérer comme failure pour l'attente
            log_audit_event(conn, 'PROCESSING_END', status='FAILURE', customer_id=customer_id, 
                           details=f"Feedback analysis failed: {summary}")
            continue  # Passer au suivant
        else:
            # Analyse générée avec succès
            analyses_to_insert.append((customer_id, summary, sentiment, topics))
            log_audit_event(conn, 'ANALYSIS_GENERATED', status='SUCCESS', customer_id=customer_id, 
                           details=f"Summary: '{summary[:60]}...', Sentiment: {sentiment}")
            print(f"   Analysis generated: Summary: '{summary[:80]}...'")
            print(f"   Sentiment: {sentiment}, Topics: {topics}")
            processed_in_batch += 1
            log_audit_event(conn, 'PROCESSING_END', status='SUCCESS', customer_id=customer_id)

    # Insérer les analyses générées pour ce lot
    if analyses_to_insert:
        insert_query = """
        INSERT INTO feedback_analysis (customer_id, feedback_summary, sentiment, key_topics) 
        VALUES (%s, %s, %s, %s) ON CONFLICT (customer_id) DO NOTHING;
        """
        try:
            with conn.cursor() as cur:
                cur.executemany(insert_query, analyses_to_insert)
            conn.commit()  # Commit après l'insertion réussie du lot
            log_audit_event(conn, 'DB_SAVE', status='SUCCESS', details=f"Inserted {len(analyses_to_insert)} analyses.")
            print(f"\n[{AGENT_NAME}] Inserted {len(analyses_to_insert)} new analyses.")
            # Petite pause après un batch réussi avec appels API
            if not api_related_failure:  # Ne pas pauser si on s'est arrêté pour rate limit
                time.sleep(1.0)
        except psycopg2.Error as db_err:
            log_audit_event(conn, 'DB_SAVE', status='FAILURE', details=f"Analysis insert failed for batch: {db_err}")
            print(f"   ERROR [{AGENT_NAME}]: DB Error inserting analyses batch: {db_err}")
            conn.rollback()
            log_audit_event(conn, 'BATCH_END', status='FAILURE', details="Batch failed during DB save.")
            return True  # Erreur DB

    log_audit_event(conn, 'BATCH_END', status='INFO' if not api_related_failure else 'INTERRUPTED', 
                   details=f"Finished analysis batch. Generated/Saved {len(analyses_to_insert)} analyses. API failure encountered: {api_related_failure}")
    print(f"[{AGENT_NAME}] Finished batch processing.")
    return api_related_failure

# --- Boucle Principale de l'Agent ---
if __name__ == "__main__":
    print(f"[{AGENT_NAME}] Agent starting up...")
    db_conn = connect_db()

    while True:
        error_occurred = False  # Inclut rate limit pour l'attente
        try:
            if db_conn is None or db_conn.closed:
                print(f"WARNING [{AGENT_NAME}]: Database connection found closed. Reconnecting...")
                log_audit_event(db_conn, 'DB_CONNECT', status='WARNING', details='Connection lost, attempting reconnect.')
                db_conn = connect_db()

            error_occurred = process_feedback_for_analysis(db_conn)

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