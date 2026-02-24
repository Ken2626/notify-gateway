FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY gateway ./gateway
COPY scripts ./scripts

ENV PYTHONUNBUFFERED=1
ENV PORT=8080

EXPOSE 8080

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
