FROM python:3.9-slim
WORKDIR /app

# Désactiver explicitement toutes les variables d'environnement de proxy
ENV HTTP_PROXY=""
ENV HTTPS_PROXY=""
ENV http_proxy=""
ENV https_proxy=""
ENV no_proxy=""
ENV NO_PROXY=""

# Copier d'abord requirements.txt pour utiliser le cache Docker si les dépendances ne changent pas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le reste de l'application
COPY agent.py .

# Assure que les prints apparaissent immédiatement dans les logs Docker
ENV PYTHONUNBUFFERED=1

# Commande d'exécution de l'agent
CMD ["python", "agent.py"]