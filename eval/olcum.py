"""Arama kalitesini ölçer: her soru için doğru kod parçası kaçıncı sırada bulunuyor?

Kullanım:  python -m eval.olcum            (proje kökünden)
Ölçütler:
  - İlk 1'de isabet: doğru parça en üstte mi?
  - İlk 5'te isabet: doğru parça ilk 5 sonuçta mı? (LLM'e 5 parça gönderiliyor)
  - MRR: doğru parçanın sırasının tersi ortalaması (1. sıra=1, 2. sıra=0.5 ...)
"""
import sys
from pathlib import Path

import yaml

from src.config import load_config
from src.indexer import get_client, search

sys.stdout.reconfigure(encoding="utf-8")
K = 5


def rank_of(hits: list[dict], expected: list[str]) -> int | None:
    """Beklenen parçalardan ilkinin sırası (1'den başlar); yoksa None."""
    for i, h in enumerate(hits, 1):
        if h["name"] in expected:
            return i
    return None


def main():
    data = yaml.safe_load(open(Path(__file__).parent / "sorular.yaml", encoding="utf-8"))
    cfg = load_config()
    client = get_client(cfg)
    rows = []
    for q in data["sorular"]:
        hits = search(client, cfg, data["repo"], q["soru"], K)
        r = rank_of(hits, q["beklenen"])
        rows.append((q["dil"], r))
        mark = f"{r}. sırada" if r else "bulunamadı"
        print(f"[{q['dil']}] {mark:<12} {q['soru']}")

    print()
    for label, sel in (("Türkçe", "tr"), ("İngilizce", "en"), ("Toplam", None)):
        rs = [r for d, r in rows if sel is None or d == sel]
        top1 = sum(1 for r in rs if r == 1) / len(rs)
        top5 = sum(1 for r in rs if r and r <= K) / len(rs)
        mrr = sum(1 / r for r in rs if r) / len(rs)
        print(f"{label:<10} ilk 1: %{top1*100:3.0f}   ilk 5: %{top5*100:3.0f}   MRR: {mrr:.2f}   ({len(rs)} soru)")


if __name__ == "__main__":
    main()
