FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN mkdir -p /models
COPY som_trained_snapshot.json /models/som_trained_snapshot.json

COPY main.py .

EXPOSE 8100

CMD ["python", "main.py"]
