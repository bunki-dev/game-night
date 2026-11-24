FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 GAMENIGHT_WEB_DIST=/app/web/dist
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir ".[all]"
COPY --from=web /web/dist /app/web/dist
RUN useradd --create-home app
USER app
EXPOSE 8000
# One process on purpose: rooms live in memory (see README, "Scaling").
CMD ["sh", "-c", "uvicorn gamenight.app:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
