import streamlit as st
import pandas as pd
import psycopg2
import os
from dotenv import load_dotenv # Pourrait être utile si on charge des clés API locales pour le dashboard
import time
from datetime import datetime

# Configurer la page Streamlit en premier
st.set_page_config(layout="wide", page_title="POC Churn Dashboard", initial_sidebar_state="expanded")

# Charger les variables d'environnement (optionnel pour le dashboard s'il n'utilise pas de clés API)
# load_dotenv('/app/.env')

# Config DB (lue depuis l'environnement du conteneur, passé par docker-compose)
DB_NAME = os.getenv("POSTGRES_DB", "pocdb")
DB_USER = os.getenv("POSTGRES_USER", "pocuser")
DB_PASS = os.getenv("POSTGRES_PASSWORD", "pocpassword")
DB_HOST = os.getenv("DB_HOST", "db") # Nom du service Docker Compose
DB_PORT = os.getenv("DB_PORT", "5432")

# --- Gestion Connexion DB avec Cache Streamlit ---
# Utiliser le cache de Streamlit pour éviter de se reconnecter constamment
# ttl=10 signifie que la connexion sera considérée comme fraîche pendant 10s max
# allow_output_mutation=True est souvent nécessaire pour les objets de connexion DB
# show_spinner=False évite d'afficher un spinner à chaque réutilisation de la connexion
@st.cache_resource(ttl=10, show_spinner=False)
def init_connection():
    """Initialise et retourne une connexion à la base de données."""
    print(f"UI ({datetime.now()}): Attempting DB Connection to {DB_HOST}...")
    try:
        conn = psycopg2.connect(
            dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST, port=DB_PORT,
            connect_timeout=3 # Timeout court pour l'interface
        )
        print(f"UI ({datetime.now()}): DB Connected.")
        return conn
    except psycopg2.OperationalError as e:
        # Afficher une seule fois l'erreur via st.error pour ne pas spammer l'UI
        # On ne peut pas utiliser st.error ici car @st.cache_resource ne peut pas avoir d'output Streamlit direct
        print(f"UI ({datetime.now()}): DB Connection Error - {e}")
        return None # Retourner None en cas d'échec

# --- Exécution des requêtes avec Cache de Données ---
# ttl=5 signifie que les données seront rafraîchies toutes les 5 secondes si la page est active
# show_spinner=True affiche un message pendant le chargement des données
@st.cache_data(ttl=5, show_spinner="Chargement des données...")
def run_query(query: str, params=None):
    """Exécute une requête SQL (potentiellement paramétrée) et retourne un DataFrame Pandas."""
    # Important : Passer _conn comme argument pour que st.cache_data le prenne en compte
    # et invalide le cache si la ressource de connexion change (ou échoue).
    _conn = init_connection()
    if _conn is None:
        # Afficher un avertissement persistant si la connexion échoue
        st.warning("⚠️ Connexion à la base de données indisponible. Les données affichées peuvent être anciennes ou incomplètes.", icon="🚨")
        return pd.DataFrame() # Retourner un DataFrame vide

    try:
        # Utiliser with pour garantir la fermeture du curseur
        with _conn.cursor() as cur:
            cur.execute(query, params)
            # Vérifier si la requête a renvoyé des colonnes avant de fetch
            if cur.description:
                # Récupérer les noms de colonnes depuis la description du curseur
                colnames = [desc[0] for desc in cur.description]
                df = pd.DataFrame(cur.fetchall(), columns=colnames)
                # Convertir les timestamps en objets datetime pour un meilleur formatage
                for col in df.select_dtypes(include=['datetime64[ns, UTC]', 'datetime64[ns]']).columns:
                     # Convertir en timezone locale (ou laisser en UTC si préférable)
                     try:
                         df[col] = pd.to_datetime(df[col]).dt.tz_convert(None) # Ou dt.tz_localize(None) si déjà naive
                     except TypeError: # Gérer le cas où c'est déjà naive
                          df[col] = pd.to_datetime(df[col])

                return df
            else:
                # Si la requête ne renvoie rien (ex: UPDATE sans RETURNING), retourner DF vide
                return pd.DataFrame()
    except (psycopg2.InterfaceError, psycopg2.OperationalError) as db_error:
        # Si la connexion est perdue pendant l'exécution
        print(f"UI ({datetime.now()}): DB Error during query - {db_error}. Invalidating connection cache.")
        st.warning(f"⚠️ Erreur base de données lors de la requête. Tentative de rafraîchissement automatique... ({db_error})", icon="🔄")
        # Invalider la ressource de connexion pour forcer la réinitialisation au prochain run
        init_connection.clear()
        # Attendre un court instant avant que Streamlit ne relance automatiquement
        time.sleep(1)
        st.rerun() # Demander à Streamlit de réexécuter le script
    except Exception as e:
         print(f"UI ({datetime.now()}): Unexpected error during query execution - {e}")
         st.error(f"Une erreur inattendue est survenue lors de la récupération des données : {e}")
         return pd.DataFrame()


# --- Interface Streamlit ---
st.title("📊 Dashboard POC - Prédiction Churn & Actions IA (avec Audit)")
st.caption(f"Démonstration d'architecture avec Agents IA, Docker, Groq et principes de gouvernance/audit. Données mises à jour ~ toutes les 5 secondes.")

# Indicateur de statut de la connexion DB dans la sidebar
conn_status = init_connection()
st.sidebar.title("Statut")
if conn_status and not conn_status.closed:
    st.sidebar.success("🟢 Base de données connectée")
else:
    st.sidebar.error("🔴 Base de données déconnectée")
# Bouton pour forcer le rafraîchissement (invalide les caches)
if st.sidebar.button("🔄 Rafraîchir Maintenant"):
    st.cache_data.clear()
    st.cache_resource.clear()
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("Filtres (Exemple)")
# Exemple de filtre (non fonctionnel ici sans logique de filtrage des requêtes)
selected_segment = st.sidebar.selectbox("Segment de Risque", ["Tous", "High Risk", "Medium Risk", "Low Risk"])
# Pour filtrer, il faudrait passer selected_segment à run_query et ajouter une clause WHERE

# --- Onglets pour organiser l'information ---
tab1, tab2, tab3 = st.tabs(["👤 Clients & Feedback", "📈 Prédictions & Actions", "📜 Audit Log"])

with tab1:
    st.header("Clients & Analyse Feedback (Données Synthétiques)")
    # Jointure pour afficher client, consentement et analyse NLP si disponible
    query_clients_nlp = """
    SELECT
        c.customer_id,
        c.name,
        c.consent_given, -- Afficher le statut du consentement
        c.last_activity_days,
        c.complaints_count,
        c.feedback_text,
        fa.sentiment,
        fa.key_topics,
        fa.feedback_summary,
        fa.analyzed_at
    FROM customers c
    LEFT JOIN feedback_analysis fa ON c.customer_id = fa.customer_id
    ORDER BY c.customer_id;
    """
    df_clients = run_query(query_clients_nlp)
    # Améliorer l'affichage du booléen
    if 'consent_given' in df_clients.columns:
        df_clients['consent_given'] = df_clients['consent_given'].map({True: '✅ Oui', False: '❌ Non', None: 'N/A'})
    # Formatter la date d'analyse
    if 'analyzed_at' in df_clients.columns:
        df_clients['analyzed_at'] = pd.to_datetime(df_clients['analyzed_at']).dt.strftime('%Y-%m-%d %H:%M:%S')

    st.dataframe(df_clients, use_container_width=True, height=300, hide_index=True)

with tab2:
    st.header("Prédictions Churn & Actions Recommandées")
    # Jointure pour afficher prédictions et actions si disponibles
    query_preds_actions = """
    SELECT
        p.customer_id,
        p.churn_probability,
        a.segment AS risk_segment,
        a.recommended_action,
        p.predicted_at,
        a.processed_at AS action_processed_at
    FROM predictions p
    LEFT JOIN actions a ON p.customer_id = a.customer_id
    ORDER BY p.churn_probability DESC NULLS LAST, p.predicted_at DESC;
    """
    df_actions = run_query(query_preds_actions)

    # Configuration de la colonne de probabilité
    column_config = {
        "customer_id": st.column_config.NumberColumn("Cust ID"),
        "churn_probability": st.column_config.ProgressColumn(
            "Prob. Churn",
            help="Probabilité de départ du client (0% = reste, 100% = part)",
            format="%.1f%%", # Affichage en pourcentage
            min_value=0,
            max_value=1, # La probabilité est entre 0 et 1
        ),
         "risk_segment": st.column_config.TextColumn("Segment Risque"),
         "recommended_action": st.column_config.TextColumn("Action Recommandée"),
         "predicted_at": st.column_config.DatetimeColumn(
             "Prédit le",
             format="YYYY-MM-DD HH:mm:ss"
          ),
         "action_processed_at": st.column_config.DatetimeColumn(
              "Action Traitée le",
              format="YYYY-MM-DD HH:mm:ss"
          )
    }

    st.dataframe(df_actions, use_container_width=True, height=300, column_config=column_config, hide_index=True)


with tab3:
    st.header("Audit Log (Derniers Événements)")
    st.caption("Trace des événements clés pour la gouvernance et le suivi des agents.")

    # Filtres pour l'audit log
    col1, col2, col3 = st.columns(3)
    with col1:
        agent_filter = st.selectbox("Filtrer par Agent", ["Tous", "nlp", "prediction", "action"], key="agent_filter")
    with col2:
        status_filter = st.selectbox("Filtrer par Statut", ["Tous", "SUCCESS", "FAILURE", "ERROR", "WARNING", "INFO", "INTERRUPTED", "SKIPPED"], key="status_filter")
    with col3:
        limit_filter = st.number_input("Nombre max d'entrées", min_value=10, max_value=1000, value=100, step=10, key="limit_filter")


    # Construire la requête dynamiquement
    query_audit = """
    SELECT log_id, log_timestamp, agent_name, event_type, status, customer_id, details
    FROM audit_log
    """
    filters = []
    params = []
    if agent_filter != "Tous":
        filters.append("agent_name = %s")
        params.append(agent_filter)
    if status_filter != "Tous":
        filters.append("status = %s")
        params.append(status_filter)

    if filters:
        query_audit += " WHERE " + " AND ".join(filters)

    query_audit += " ORDER BY log_timestamp DESC LIMIT %s;"
    params.append(limit_filter)

    df_audit = run_query(query_audit, tuple(params))

    # Formatter le timestamp pour meilleure lisibilité
    audit_column_config = {
         "log_id": st.column_config.NumberColumn("Log ID"),
         "log_timestamp": st.column_config.DatetimeColumn(
               "Timestamp",
               format="YYYY-MM-DD HH:mm:ss.SSS Z" # Format détaillé avec timezone
         ),
          "agent_name": st.column_config.TextColumn("Agent"),
          "event_type": st.column_config.TextColumn("Événement"),
          "status": st.column_config.TextColumn("Statut"),
          "customer_id": st.column_config.NumberColumn("Cust ID"),
          "details": st.column_config.TextColumn("Détails"),
    }
    st.dataframe(df_audit, use_container_width=True, height=500, column_config=audit_column_config, hide_index=True)


st.sidebar.markdown("---")
st.sidebar.info(f"Dernière màj UI: {datetime.now().strftime('%H:%M:%S')}")
