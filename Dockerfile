# One image for the UI and the API (docker compose up --build)
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LABASSIST_CHROMA_DIR=/app/chroma \
    LABASSIST_DB=/data/labassist.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# build the search index now so startup is fast
RUN python -c "from core.rag import get_retriever; r = get_retriever(); assert r.vector_ok, r.vector_error; print(r.status())"

EXPOSE 8501 8000
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
