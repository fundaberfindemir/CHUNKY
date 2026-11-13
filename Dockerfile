# Kod Tabanıyla Sohbet (Chunky) - Docker imajı
# Not: API anahtarları imaja girmez; compose.yaml çalışırken .env'den verir.
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# git: GitHub repolarını klonlamak için, ca-certificates: HTTPS bağlantıları için
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# İsteğe bağlı ek kök sertifikalar (antivirüs/kurumsal ağ HTTPS denetimi için, bkz. certs/README.md).
# certs/ içinde .crt yoksa hiçbir şey değişmez.
COPY certs/ /tmp/certs/
RUN find /tmp/certs -name '*.crt' -exec cp {} /usr/local/share/ca-certificates/ \; \
    && update-ca-certificates \
    && rm -rf /tmp/certs
# pip, httpx ve git sistemin sertifika deposunu kullansın
ENV PIP_CERT=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Uygulama root olmayan bir kullanıcıyla çalışır
RUN useradd --create-home --uid 1000 app
WORKDIR /app

# Önce bağımlılıklar: kod değişince bu katman önbellekten gelir
COPY requirements.txt .
RUN pip install -r requirements.txt

RUN mkdir -p /app/repos && chown -R app:app /app
USER app

# Embedding modellerini (~240 MB, çok dilli + BM25) derleme sırasında indir; ilk indekslemede beklenmesin
ENV FASTEMBED_CACHE_PATH=/home/app/.cache/fastembed
COPY --chown=app:app config.yaml .
RUN python -c "import yaml; from fastembed import TextEmbedding as D, SparseTextEmbedding as S; c = yaml.safe_load(open('config.yaml', encoding='utf-8'))['vector_db']; list(D(c['dense_model']).embed(['hazir'])); list(S(c['sparse_model']).embed(['hazir']))"

COPY --chown=app:app . .

EXPOSE 8501

# Streamlit'in sağlık adresi yanıt veriyor mu?
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501"]
