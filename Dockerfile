FROM prom/alertmanager:v0.27.0 AS alertmanager

FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY src ./src
COPY scripts ./scripts

COPY --from=alertmanager /bin/alertmanager /usr/local/bin/alertmanager

RUN chmod +x /usr/local/bin/alertmanager /app/scripts/entrypoint.sh

ENV NODE_ENV=production
ENV PORT=8080
ENV ALERTMANAGER_PORT=9093

EXPOSE 8080

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
