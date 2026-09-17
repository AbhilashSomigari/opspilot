FROM python:3.12-slim
ARG SERVICE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 SERVICE=${SERVICE}
WORKDIR /workspace
COPY . /workspace
RUN pip install --no-cache-dir "."
CMD ["sh", "-c", "uvicorn services.${SERVICE}.app.main:app --host 0.0.0.0 --port 8000"]
