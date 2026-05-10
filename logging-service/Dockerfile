FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY logging-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY logging-service/src/ ./src/
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "4000"]
