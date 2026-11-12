"""Komut satırı aracı.

Kullanım:
  python cli.py index https://github.com/kisi/proje
  python cli.py search kisi__proje "token nasıl doğrulanıyor?"
  python cli.py ask kisi__proje "token nasıl doğrulanıyor?" [--provider ollama]
  python cli.py list
"""
import argparse
import sys
import time

from src.config import load_config, resolve_path
from src.indexer import get_client, index_repo, list_repos, search
from src.llm import LLMError
from src.rag import answer
from src.repo_loader import RepoError, clone_repo

# Windows konsolunda Türkçe karakterler bozulmasın
sys.stdout.reconfigure(encoding="utf-8")


def cmd_index(args, cfg, client):
    t = time.time()
    try:
        repo_path = clone_repo(args.url, resolve_path(cfg, "repos_dir"))
        n = index_repo(repo_path, cfg, client)
    except RepoError as e:
        print(f"[hata] {e}")
        sys.exit(1)
    print(f"[indeks] {repo_path.name}: {n} chunk, {time.time() - t:.1f} sn")


def cmd_search(args, cfg, client):
    hits = search(client, args.repo, args.query, args.k or cfg["search"]["top_k"])
    print(f'\nSoru: "{args.query}"\n')
    for i, h in enumerate(hits, 1):
        print(f"{i}. [{h['score']:.3f}] {h['file_path']}:{h['start_line']}-{h['end_line']}"
              f"  ({h['kind']}) {h['name']}")
        if args.show_code:
            preview = "\n".join(h["code"].splitlines()[:8])
            print("   " + preview.replace("\n", "\n   ") + "\n")


def cmd_ask(args, cfg, client):
    try:
        res = answer(args.question, args.repo, cfg, client, provider=args.provider)
    except LLMError as e:
        print(f"[hata] {e}")
        sys.exit(1)
    print(f"\n{res['answer']}\n\nKaynaklar:")
    for h in res["sources"]:
        print(f"  - {h['file_path']}:{h['start_line']}-{h['end_line']} ({h['name']})")


def main():
    p = argparse.ArgumentParser(description="Kod Tabanıyla Sohbet - CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("index", help="Repoyu klonla ve indeksle")
    pi.add_argument("url")

    ps = sub.add_parser("search", help="Benzerlik araması yap")
    ps.add_argument("repo", help="Repo adı (list ile görebilirsiniz)")
    ps.add_argument("query")
    ps.add_argument("-k", type=int, help="Kaç sonuç dönsün")
    ps.add_argument("--show-code", action="store_true", help="Kod önizlemesi göster")

    pa = sub.add_parser("ask", help="LLM ile kaynaklı cevap al (RAG)")
    pa.add_argument("repo")
    pa.add_argument("question")
    pa.add_argument("--provider", choices=["claude", "gemini", "ollama"],
                    help="config.yaml'daki sağlayıcıyı geçersiz kıl")

    sub.add_parser("list", help="İndekslenmiş repoları listele")

    args = p.parse_args()
    cfg = load_config()
    client = get_client(resolve_path(cfg, "db_dir"))

    if args.cmd == "index":
        cmd_index(args, cfg, client)
    elif args.cmd == "search":
        cmd_search(args, cfg, client)
    elif args.cmd == "ask":
        cmd_ask(args, cfg, client)
    else:
        for name in list_repos(client):
            print(name)


if __name__ == "__main__":
    main()
