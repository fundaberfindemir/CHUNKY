"""GitHub reposunu klonlar ve indekslenecek Python dosyalarını listeler."""
import re
import shutil
from pathlib import Path

from git import GitCommandError, Repo


class RepoError(Exception):
    """Kullanıcıya gösterilebilecek, anlaşılır repo hatası."""


def repo_name_from_url(url: str) -> str:
    """'https://github.com/kisi/proje.git' -> 'kisi__proje'"""
    m = re.search(r"github\.com[/:]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", url.strip())
    if not m:
        raise RepoError("Bu bir GitHub repo adresi gibi görünmüyor. Örnek: https://github.com/kisi/proje")
    return f"{m.group(1)}__{m.group(2)}"


def clone_repo(url: str, repos_dir: Path) -> Path:
    """Repoyu klonlar; zaten varsa yeniden indirmez."""
    target = repos_dir / repo_name_from_url(url)
    if target.exists():
        print(f"[klon] Zaten var, atlanıyor: {target.name}")
        return target
    repos_dir.mkdir(parents=True, exist_ok=True)
    print(f"[klon] İndiriliyor: {url}")
    try:
        # depth=1: sadece son commit, hızlı ve küçük
        Repo.clone_from(url.strip(), target, depth=1)
    except GitCommandError:
        shutil.rmtree(target, ignore_errors=True)  # yarım kalan klonu temizle
        raise RepoError("Repo indirilemedi. Adresin doğru olduğundan ve reponun herkese açık "
                        "olduğundan emin olun.") from None
    return target


def list_source_files(repo_path: Path, cfg: dict) -> list[Path]:
    """Gereksiz klasörleri atlayarak kaynak dosyaları bulur."""
    ignore = set(cfg["indexing"]["ignore_dirs"])
    exts = set(cfg["indexing"]["extensions"])
    max_bytes = cfg["indexing"]["max_file_kb"] * 1024

    files = []
    for path in repo_path.rglob("*"):
        rel_parts = path.relative_to(repo_path).parts
        # Yolun herhangi bir parçası yok sayılan bir klasörse atla
        if any(part in ignore for part in rel_parts):
            continue
        if path.is_file() and path.suffix in exts and path.stat().st_size <= max_bytes:
            files.append(path)
    return sorted(files)
