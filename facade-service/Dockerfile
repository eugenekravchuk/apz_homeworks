FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY facade-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY facade-service/src/ ./src/
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "3000"]
