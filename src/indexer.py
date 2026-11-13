"""Kod parçalarını Qdrant'a yazar ve KARMA arama yapar.

Her parça iki vektörle saklanır:
  - "anlam"  : çok dilli embedding (Türkçe ve İngilizce soruları anlar)
  - "kelime" : BM25 seyrek vektörü (`URLSafeSerializer` gibi tam adları yakalar)
Arama sırasında iki sonuç listesi Qdrant'ın RRF yöntemiyle birleştirilir.
Embedding modelleri yereldir (FastEmbed); indekslenen kod bilgisayardan çıkmaz.
"""
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import QdrantClient, models

from src.chunker import Chunk, chunk_file
from src.config import ROOT  # truststore'u da etkinleştirir (model indirme için)
from src.repo_loader import RepoError, list_source_files

DENSE, SPARSE = "anlam", "kelime"
BATCH = 32

# İlerleme bildirimi: progress(adim_no, oran 0-1, ayrinti_metni)
# Adımlar: 0 indirme (arayüzde), 1 okuma, 2 parçalama, 3 indeksleme
_noop = lambda *a: None  # noqa: E731


# ---------------- Bağlantı ve modeller ----------------
def get_client(cfg: dict) -> QdrantClient:
    """Qdrant'a bağlanır. Docker'da QDRANT_URL ortam değişkeni kullanılır."""
    url = os.getenv("QDRANT_URL") or cfg["vector_db"]["url"]
    return QdrantClient(url=url, timeout=60)


def _cache_dir() -> str:
    """Modeller bir kez indirilir ve burada saklanır."""
    return os.getenv("FASTEMBED_CACHE_PATH") or str(ROOT / ".models")


@lru_cache(maxsize=4)
def _dense(name: str) -> TextEmbedding:
    return TextEmbedding(name, cache_dir=_cache_dir())


@lru_cache(maxsize=4)
def _sparse(name: str) -> SparseTextEmbedding:
    return SparseTextEmbedding(name, cache_dir=_cache_dir())


def _to_sparse(v) -> models.SparseVector:
    return models.SparseVector(indices=v.indices.tolist(), values=v.values.tolist())


# ---------------- Yardımcılar ----------------
def collection_name(repo_name: str) -> str:
    """Koleksiyon adı: harf, rakam, nokta, alt çizgi ve tire."""
    name = re.sub(r"[^a-zA-Z0-9._-]", "-", repo_name).strip("-._")
    return name[:60] or "repo"


def _document(c: Chunk) -> str:
    """Embedding'e giden metin: başa yol ve ad eklenir ki aramada da işe yarasın."""
    return f"# {c.file_path} | {c.kind} {c.name}\n{c.code}"


def _is_test(path: str) -> bool:
    """tests/ klasörü veya test_*.py / *_test.py dosyası mı?"""
    parts = path.lower().split("/")
    return any(p in ("test", "tests", "testing") for p in parts[:-1]) or \
        parts[-1].startswith("test_") or parts[-1].endswith("_test.py")


def _point_id(c: Chunk) -> str:
    return str(uuid.UUID(c.id))  # chunk kimliği (md5) -> kararlı UUID


# ---------------- İndeksleme ----------------
def index_repo(repo_path: Path, cfg: dict, client: QdrantClient, progress=_noop) -> int:
    """Repodaki tüm Python dosyalarını parçalar ve indeksler. Parça sayısını döndürür."""
    name = collection_name(repo_path.name)
    vcfg = cfg["vector_db"]

    progress(1, 0.0, "Python dosyaları aranıyor")
    files = list_source_files(repo_path, cfg)
    if not files:
        raise RepoError("Bu repoda indekslenecek Python dosyası bulunamadı. "
                        "Şimdilik yalnızca Python repoları destekleniyor.")
    progress(1, 1.0, f"{len(files)} dosya bulundu")

    max_lines = cfg["indexing"]["max_chunk_lines"]
    chunks: list[Chunk] = []
    for n, f in enumerate(files, 1):
        try:
            chunks += chunk_file(f, repo_path, max_lines)
        except Exception as e:  # bozuk dosya tüm indekslemeyi durdurmasın
            print(f"[uyarı] {f.name} atlandı: {e}")
        progress(2, n / len(files), f"{n}/{len(files)} dosya · {len(chunks)} parça")

    progress(3, 0.0, "Modeller hazırlanıyor")
    dense, sparse = _dense(vcfg["dense_model"]), _sparse(vcfg["sparse_model"])
    dim = len(next(iter(dense.passage_embed(["boyut"]))))

    # Temiz başlangıç: aynı repo tekrar indekslenirse eskisini sil
    if client.collection_exists(name):
        client.delete_collection(name)
    client.create_collection(
        name,
        vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
    )
    # Filtrelenecek alanlar için indeks (ör. "testleri hariç tut")
    client.create_payload_index(name, "is_test", models.PayloadSchemaType.BOOL)
    client.create_payload_index(name, "kind", models.PayloadSchemaType.KEYWORD)

    for i in range(0, len(chunks), BATCH):
        progress(3, i / len(chunks), f"{i}/{len(chunks)} parça")
        part = chunks[i:i + BATCH]
        docs = [_document(c) for c in part]
        dvecs = list(dense.passage_embed(docs))
        svecs = list(sparse.embed(docs))
        client.upsert(name, points=[
            models.PointStruct(
                id=_point_id(c),
                vector={DENSE: d.tolist(), SPARSE: _to_sparse(s)},
                payload={**c.to_dict(), "is_test": _is_test(c.file_path)},
            )
            for c, d, s in zip(part, dvecs, svecs)
        ])
    progress(3, 1.0, f"{len(chunks)} parça indekslendi")
    return len(chunks)


# ---------------- Arama ----------------
def search(client: QdrantClient, cfg: dict, repo_name: str, query: str, top_k: int = 5,
           exclude_tests: bool = False) -> list[dict]:
    """Karma arama. Her sonuçta 'score' (anlam benzerliği, 0-1) ve 'match' (nasıl bulundu) olur."""
    name = collection_name(repo_name)
    vcfg = cfg["vector_db"]
    qd = next(iter(_dense(vcfg["dense_model"]).query_embed([query]))).tolist()
    qs = _to_sparse(next(iter(_sparse(vcfg["sparse_model"]).query_embed([query]))))
    flt = models.Filter(must=[models.FieldCondition(key="is_test", match=models.MatchValue(value=False))]) \
        if exclude_tests else None
    pool = max(20, top_k * 4)

    # Tek istekte üç sorgu: birleşik sonuç + ayrı ayrı anlam ve kelime (etiketlemek için)
    fused, by_dense, by_sparse = client.query_batch_points(name, requests=[
        models.QueryRequest(
            prefetch=[models.Prefetch(query=qd, using=DENSE, limit=pool, filter=flt),
                      models.Prefetch(query=qs, using=SPARSE, limit=pool, filter=flt)],
            query=models.FusionQuery(fusion=models.Fusion.RRF), limit=top_k, with_payload=True),
        models.QueryRequest(query=qd, using=DENSE, limit=pool, filter=flt),
        models.QueryRequest(query=qs, using=SPARSE, limit=pool, filter=flt),
    ])
    dense_scores = {p.id: p.score for p in by_dense.points}
    sparse_ids = {p.id for p in by_sparse.points}

    hits = []
    for p in fused.points:
        in_d, in_s = p.id in dense_scores, p.id in sparse_ids
        match = "anlam + kelime" if in_d and in_s else "anlam" if in_d else "kelime"
        score = dense_scores.get(p.id)
        hits.append({**p.payload, "score": round(score, 3) if score is not None else None, "match": match})
    return hits


# ---------------- Bilgi ----------------
def repo_stats(client: QdrantClient, repo_name: str) -> dict:
    """Arayüz kartları için: dosya sayısı ve türlere göre parça sayıları."""
    name = collection_name(repo_name)
    files, out, offset = set(), {"function": 0, "class": 0, "method": 0, "module": 0}, None
    while True:
        points, offset = client.scroll(name, limit=256, offset=offset, with_payload=["file_path", "kind"])
        for p in points:
            files.add(p.payload["file_path"])
            out[p.payload["kind"]] = out.get(p.payload["kind"], 0) + 1
        if offset is None:
            break
    return {"files": len(files), "total": sum(out.values()), **out}


def list_repos(client: QdrantClient) -> list[str]:
    """İndekslenmiş repo (koleksiyon) adları."""
    return sorted(c.name for c in client.get_collections().collections)
