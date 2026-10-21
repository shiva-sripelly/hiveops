# Builds the React frontend, then serves it from the FastAPI backend in one image.

FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/hiveops ./hiveops
RUN pip install --no-cache-dir .
COPY --from=frontend /app/dist /app/static
ENV STATIC_DIR=/app/static PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "hiveops.main:app", "--host", "0.0.0.0", "--port", "8000"]
