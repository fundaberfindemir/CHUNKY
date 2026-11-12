"""Chunk'ları ChromaDB'ye yazar ve benzerlik araması yapar.

Embedding için ChromaDB'nin yerleşik yerel modeli (all-MiniLM-L6-v2) kullanılır;
API anahtarı gerekmez. İlk çalıştırmada model bir kez indirilir.
"""
import re
from pathlib import Path

import chromadb

from src.chunker import Chunk, chunk_file
from src.repo_loader import RepoError, list_source_files

# İlerleme bildirimi: progress(adim_no, oran 0-1, ayrinti_metni)
# Adımlar: 0 indirme (arayüzde), 1 okuma, 2 parçalama, 3 indeksleme
_noop = lambda *a: None  # noqa: E731


def collection_name(repo_name: str) -> str:
    """ChromaDB koleksiyon adı kurallarına uygun hale getirir."""
    name = re.sub(r"[^a-zA-Z0-9._-]", "-", repo_name).strip("-._")
    return name[:60] or "repo"


def _document(c: Chunk) -> str:
    """Embedding'e giden metin: başa yol ve ad eklenir ki aramada da işe yarasın."""
    return f"# {c.file_path} | {c.kind} {c.name}\n{c.code}"


def get_client(db_dir: Path) -> chromadb.ClientAPI:
    db_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(db_dir))


def index_repo(repo_path: Path, cfg: dict, client, progress=_noop) -> int:
    """Repodaki tüm Python dosyalarını parçalar ve indeksler. Chunk sayısını döndürür."""
    name = collection_name(repo_path.name)

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

    # Temiz başlangıç: aynı repo tekrar indekslenirse eskisini sil
    if name in [c.name for c in client.list_collections()]:
        client.delete_collection(name)
    col = client.create_collection(name, metadata={"hnsw:space": "cosine"})

    # ChromaDB'ye partiler halinde ekle
    batch = 50
    for i in range(0, len(chunks), batch):
        progress(3, i / len(chunks), f"{i}/{len(chunks)} parça")
        part = chunks[i:i + batch]
        col.add(
            ids=[c.id for c in part],
            documents=[_document(c) for c in part],
            metadatas=[{
                "file_path": c.file_path,
                "start_line": c.start_line,
                "end_line": c.end_line,
                "name": c.name,
                "kind": c.kind,
                "code": c.code,
            } for c in part],
        )
    progress(3, 1.0, f"{len(chunks)} parça indekslendi")
    return len(chunks)


def search(client, repo_name: str, query: str, top_k: int = 5) -> list[dict]:
    """Soruya en benzer chunk'ları döndürür (benzerlik: 1 - kosinüs uzaklığı)."""
    col = client.get_collection(collection_name(repo_name))
    res = col.query(query_texts=[query], n_results=top_k)
    hits = []
    for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
        hits.append({**meta, "score": round(1 - dist, 3)})
    return hits


def repo_stats(client, repo_name: str) -> dict:
    """Arayüz kartları için: dosya sayısı ve türlere göre chunk sayıları."""
    col = client.get_collection(collection_name(repo_name))
    metas = col.get(include=["metadatas"])["metadatas"]
    out = {"files": len({m["file_path"] for m in metas}), "total": len(metas),
           "function": 0, "class": 0, "method": 0, "module": 0}
    for m in metas:
        out[m["kind"]] = out.get(m["kind"], 0) + 1
    return out


def list_repos(client) -> list[str]:
    """İndekslenmiş repo (koleksiyon) adları."""
    return sorted(c.name for c in client.list_collections())
