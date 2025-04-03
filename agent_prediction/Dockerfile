FROM python:3.9-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code et le modèle
COPY agent.py .
# IMPORTANT: Le fichier model.pkl doit être présent ici au moment du build
# Il est créé par un script local puis ce Dockerfile le copie dans l'image.
COPY models/churn_model_latest.pkl ./model.pkl
ENV PYTHONUNBUFFERED=1
CMD ["python", "agent.py"]
