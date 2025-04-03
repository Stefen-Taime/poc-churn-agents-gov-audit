FROM python:3.9-slim
WORKDIR /app

# Désactiver explicitement toutes les variables d'environnement de proxy
ENV HTTP_PROXY=""
ENV HTTPS_PROXY=""
ENV http_proxy=""
ENV https_proxy=""
ENV no_proxy=""
ENV NO_PROXY=""

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py .
ENV PYTHONUNBUFFERED=1

CMD ["python", "agent.py"]