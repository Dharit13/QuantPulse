# Stage 1: Build Next.js frontend
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend-next
COPY frontend-next/package.json frontend-next/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend-next/ ./
RUN npm run build

# Stage 2: Python runtime with both services
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl supervisor \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY backtest/ ./backtest/
COPY nlp/ ./nlp/
COPY scripts/ ./scripts/

COPY --from=frontend-build /app/frontend-next ./frontend-next
COPY --from=frontend-build /app/frontend-next/.next ./frontend-next/.next
COPY --from=frontend-build /app/frontend-next/node_modules ./frontend-next/node_modules

COPY supervisord.conf /etc/supervisor/conf.d/quantpulse.conf

EXPOSE 3000 8000

CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/quantpulse.conf"]
