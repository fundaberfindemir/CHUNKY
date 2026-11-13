"""RAG: soruya en benzer kod parçalarını bul, LLM'e bağlam olarak ver, kaynaklı cevap al."""
from collections.abc import Iterator

from src.indexer import search
from src.llm import ensure_ready, generate, stream

SYSTEM_PROMPT = """Sen bir kod tabanı asistanısın. Kullanıcının sorusunu SADECE sana verilen kod parçalarına dayanarak cevapla.

Kurallar:
- Her iddianın yanında kaynağı `dosya/yolu.py:baslangic-bitis` biçiminde belirt.
- Bağlamda cevap yoksa bunu açıkça söyle; uydurma.
- Gerekirse kısa kod alıntıları kullan.
- Kullanıcı hangi dilde sorduysa o dilde cevap ver."""


def build_context(hits: list[dict]) -> str:
    """Bulunan chunk'ları numaralı, kaynaklı bir metne çevirir."""
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(
            f"[{i}] {h['file_path']}:{h['start_line']}-{h['end_line']} ({h['kind']} {h['name']})\n"
            f"```python\n{h['code']}\n```"
        )
    return "\n\n".join(parts)


def _prepare(question, repo, cfg, client, provider, model, top_k, exclude_tests):
    llm_cfg = cfg["llm"]
    provider = provider or llm_cfg["provider"]
    model = model or llm_cfg["models"][provider]
    ensure_ready(provider)  # anahtar yoksa aramaya hiç başlama
    if exclude_tests is None:
        exclude_tests = cfg["search"].get("exclude_tests", False)
    hits = search(client, cfg, repo, question, top_k or cfg["search"]["top_k"], exclude_tests=exclude_tests)
    user_msg = f"Kod parçaları:\n\n{build_context(hits)}\n\nSoru: {question}"
    opts = dict(temperature=llm_cfg["temperature"], max_tokens=llm_cfg["max_tokens"],
                fallback=llm_cfg.get("fallback_models", {}).get(provider))
    return hits, user_msg, provider, model, opts


def answer(question: str, repo: str, cfg: dict, client,
           provider: str | None = None, model: str | None = None,
           top_k: int | None = None, exclude_tests: bool | None = None) -> dict:
    """Soruyu cevaplar. Dönen sözlük: {'answer': str, 'sources': list[dict]}"""
    hits, user_msg, provider, model, opts = _prepare(question, repo, cfg, client, provider, model,
                                                     top_k, exclude_tests)
    text = generate(SYSTEM_PROMPT, user_msg, provider, model, **opts)
    return {"answer": text, "sources": hits}


def answer_stream(question: str, repo: str, cfg: dict, client,
                  provider: str | None = None, model: str | None = None,
                  top_k: int | None = None, on_fallback=None,
                  exclude_tests: bool | None = None) -> tuple[list[dict], Iterator[str]]:
    """Kaynakları hemen, cevabı ise parça parça (akan yazı) döndürür."""
    hits, user_msg, provider, model, opts = _prepare(question, repo, cfg, client, provider, model,
                                                     top_k, exclude_tests)
    return hits, stream(SYSTEM_PROMPT, user_msg, provider, model, on_fallback=on_fallback, **opts)
