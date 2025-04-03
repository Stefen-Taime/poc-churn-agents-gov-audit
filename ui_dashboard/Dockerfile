FROM python:3.9-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

# Définir les variables d'environnement pour Streamlit si nécessaire
# ENV STREAMLIT_SERVER_PORT=8501
# ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
# ENV STREAMLIT_SERVER_ENABLE_CORS=false

# Assurer que les logs Python sont visibles
ENV PYTHONUNBUFFERED=1

# Exposer le port par défaut de Streamlit
EXPOSE 8501

# Commande pour lancer Streamlit, écoute sur toutes les interfaces
# Le tag --server.enableXsrfProtection=false peut être nécessaire dans certains environnements Docker, mais à utiliser avec prudence.
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
