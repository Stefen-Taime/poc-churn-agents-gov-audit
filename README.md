# POC: Churn Prediction and Retention Actions with AI Agents (Docker & Groq) - Governance & Audit Demo

This project is a Proof of Concept (POC) demonstrating how an architecture based on AI agents, orchestrated with Docker Compose, can be used to predict customer churn and generate personalized retention actions using an LLM (via the Groq API).

A particular emphasis is placed on **demonstrating data governance principles**, including an **audit trail**, even within the context of a POC using synthetic data.

## Architecture

The system consists of several containerized services:

1.  **`db` (PostgreSQL):** Stores customer data (synthetic), feedback analyses, churn predictions, recommended actions, and a dedicated **`audit_log` table**.
2.  **`agent_nlp`:**
    *   Reads customer feedback from the database.
    *   **Logs key steps** in `audit_log`.
    *   **Checks customer consent** (logged).
    *   **Anonymizes** feedback text (simulated and logged).
    *   Calls the Groq API (call logged).
    *   Stores analysis results (save logged).
3.  **`agent_prediction`:**
    *   Loads an ML model (load logged).
    *   Reads customer features.
    *   Predicts churn probability (prediction logged).
    *   Stores predictions (save logged).
4.  **`agent_segmentation_action`:**
    *   Reads predictions and analyses.
    *   Determines a risk segment.
    *   Calls the Groq API to generate an action (call logged).
    *   Stores the segment and action (save logged).
5.  **`ui_dashboard` (Streamlit):**
    *   Provides a web interface to visualize data, analyses, predictions, actions, and **the audit logs**.

## Data Governance Demonstration (in this POC)

This POC integrates several elements to demonstrate how governance would be managed in production:

1.  **Synthetic Data Only:** No real customer data is used.
2.  **Consent Verification:** The `agent_nlp` checks and logs consent status.
3.  **Simulated Anonymization:** The `agent_nlp` applies and logs the anonymization step before the external call.
4.  **Isolation of External Calls:** Only designated agents communicate with the external API.
5.  **Logging and Auditability:**
    *   A dedicated **`audit_log`** table records critical events (checks, API calls, DB saves, errors).
    *   Each agent uses a helper function to write to this table, providing a centralized audit trail.
    *   These logs are visible in the dashboard for increased transparency.
6.  **Secure Secret Management (Basic):** API key via `.env` (to be protected and replaced by Vault in production).
7.  **Transition to Production:** Reminder that Groq would be replaced by an internal/private LLM in production. In production, auditing could be handled by a dedicated agent and a message queue for more resilience and decoupling.

## Prerequisites

*   Docker
*   Docker Compose
*   A Groq API key (obtainable from [console.groq.com](https://console.groq.com/))
*   Python (to initially create the `model.pkl` model)
*   Local Python libraries: `scikit-learn`, `pandas`, `joblib` (or `pickle`) to create the model.

## Installation and Launch

1.  **Clone the repository or create the file structure.**
2.  **Create the `.env` file** at the root and add your database credentials (can remain the default ones) and your Groq API key:
    ```env
    POSTGRES_USER=pocuser
    POSTGRES_PASSWORD=pocpassword
    POSTGRES_DB=pocdb
    GROQ_API_KEY=gsk_YOUR_GROQ_API_KEY_HERE
    ```
3.  **Create the `model.pkl` model:**
    *   Execute the provided Python script `create_model.py` to generate a basic churn prediction model.
    *   The model will be saved in the `agent_prediction/` folder under the name `model.pkl`.
4.  **Build and Launch the Containers:** From the root directory `poc-churn-agents-gov-audit/`
    ```bash
    docker-compose up --build -d
    ```
    *   The `-d` flag runs containers in the background. Remove it to see all logs live.
5.  **Access the Dashboard:** Open your browser and go to `http://localhost:8501`.
6.  **Observe Docker Logs:** To see the raw activity of the agents:
    ```bash
    docker-compose logs -f agent_nlp
    docker-compose logs -f agent_prediction
    docker-compose logs -f agent_segmentation_action
    ```
7.  **Consult the Audit Log:** Via the dedicated section ("Audit Log") in the Streamlit dashboard.
8.  **Stop the Containers:**
    ```bash
    docker-compose down
    ```

## Agent Functionality

### Agent NLP
Analyzes customer feedback using the Groq API to extract sentiment, key topics, and a summary. Checks consent and anonymizes data before any external call.

### Agent Prediction
Uses a simple ML model to predict the churn probability for each customer based on features like days since last activity and number of complaints.

### Agent Segmentation & Action
Segments customers into risk categories (High, Medium, Low) and generates personalized retention actions via the Groq API, taking into account the risk segment and feedback analysis.

### Dashboard UI
Streamlit user interface allowing visualization of all data and audit logs, with filters for easier exploration.

## Important Notes

- This POC is designed to demonstrate architectural and governance principles, not to be deployed to production as is.
- The data is entirely synthetic and generated for demonstration purposes.
- In production, the Groq API would be replaced by an internal or private LLM with additional security controls.
- Secret management (.env) is simplified for this POC and should be strengthened in production.