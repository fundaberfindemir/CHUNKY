"""LLM sağlayıcı katmanı: claude | gemini | ollama.

- stream(...)   -> cevabı parça parça üretir (arayüzde akan yazı için)
- generate(...) -> cevabın tamamını tek metin olarak döndürür (CLI için)

Sağlayıcı ve model config.yaml'dan gelir; API anahtarları sadece .env'den okunur.
SDK'lar sadece seçilen sağlayıcı kullanılınca içe aktarılır (lazy import).
Hata mesajları Türkçedir ve asla anahtar ya da istek ayrıntısı içermez.
"""
import json
from collections.abc import Iterator

import httpx

from src.config import get_secret

# Her sağlayıcının ihtiyaç duyduğu ortam değişkeni (Ollama anahtarsız çalışır)
KEY_NAMES = {"gemini": "GEMINI_API_KEY", "claude": "ANTHROPIC_API_KEY", "ollama": None}
DISPLAY_NAMES = {"gemini": "Gemini", "claude": "Claude", "ollama": "Ollama"}
LOCAL_PROVIDERS = {"ollama"}  # kod bilgisayardan çıkmaz


class LLMError(RuntimeError):
    """Kullanıcıya gösterilebilecek, gizli bilgi içermeyen hata."""


def has_key(provider: str) -> bool:
    """Anahtar tanımlı mı? (Değeri asla döndürmez.)"""
    name = KEY_NAMES.get(provider)
    return name is None or get_secret(name) is not None


# Anahtarların kaba biçim kontrolü (değer asla gösterilmez). Google farklı biçimlerde
# anahtar üretebildiği için Gemini'de sadece uzunluk ve boşluk kontrol edilir.
_KEY_SHAPES = {
    "gemini": lambda k: len(k) >= 30 and not any(c.isspace() for c in k),
    "claude": lambda k: k.startswith("sk-ant-"),
}


def key_looks_valid(provider: str) -> bool:
    """Anahtar tanımlıysa, biçimi bu sağlayıcı için beklenene benziyor mu?"""
    name = KEY_NAMES.get(provider)
    if not name or provider not in _KEY_SHAPES:
        return True
    key = get_secret(name) or ""
    return _KEY_SHAPES[provider](key.strip())


def ensure_ready(provider: str) -> None:
    """İstek atmadan önce sağlayıcının kullanılabilir olduğunu kontrol eder."""
    if provider not in KEY_NAMES:
        raise LLMError(f"“{provider}” tanınan bir sağlayıcı değil. Seçenekler: gemini, claude, ollama.")
    if not has_key(provider):
        raise LLMError(f"{DISPLAY_NAMES[provider]} için API anahtarı bulunamadı. "
                       f".env dosyasına {KEY_NAMES[provider]} satırını ekleyip uygulamayı yeniden başlatın.")


def _key(provider: str) -> str:
    ensure_ready(provider)
    return get_secret(KEY_NAMES[provider])


def _friendly(e: Exception, provider: str, model: str) -> LLMError:
    """SDK hatalarını anlaşılır Türkçe mesajlara çevirir (ayrıntı sızdırmadan)."""
    name = DISPLAY_NAMES[provider]
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    text = str(e).lower()
    if isinstance(e, (httpx.ConnectError, httpx.ConnectTimeout)) or "connection" in type(e).__name__.lower():
        return LLMError(f"{name} sunucusuna ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.")
    if status in (401, 403) or "api key" in text or "api_key" in text or "permission" in text:
        return LLMError(f"{name} anahtarı kabul edilmedi. .env dosyasındaki anahtarın doğru ve etkin olduğundan emin olun.")
    if status in (500, 502, 503) or "unavailable" in text or "overloaded" in text or "high demand" in text:
        return LLMError(f"{name} şu an çok yoğun (“{model}”). Biraz sonra tekrar deneyin "
                        f"ya da kenar çubuğundan başka bir model seçin.")
    if status == 404 or "not found" in text:
        return LLMError(f"“{model}” adlı model bulunamadı. Kenar çubuğundaki model adını kontrol edin.")
    if status == 429 or "quota" in text or "rate limit" in text or "resource_exhausted" in text:
        return LLMError(f"{name} kullanım sınırına ulaşıldı. Biraz bekleyip tekrar deneyin.")
    if isinstance(e, (httpx.TimeoutException, TimeoutError)):
        return LLMError(f"{name} zamanında cevap vermedi. Biraz sonra tekrar deneyin.")
    return LLMError(f"{name} şu an cevap veremedi ({type(e).__name__}). Biraz sonra tekrar deneyin.")


def _is_transient(e: Exception) -> bool:
    """Yoğunluk/zaman aşımı gibi, başka bir modelle denemeye değer geçici hatalar."""
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    text = str(e).lower()
    return (status in (429, 500, 502, 503, 504)
            or isinstance(e, (httpx.TimeoutException, TimeoutError))
            or "unavailable" in text or "high demand" in text or "timed out" in text)


def stream(system: str, user: str, provider: str, model: str,
           temperature: float = 0.2, max_tokens: int = 1500,
           fallback: str | list[str] | None = None, on_fallback=None) -> Iterator[str]:
    """Seçilen sağlayıcıdan cevabı parça parça getirir.

    Asıl model ilk kelimeyi vermeden geçici bir hata verirse (yoğunluk, zaman aşımı)
    `fallback` listesindeki modeller sırayla denenir; her geçişte
    `on_fallback(denenen, siradaki)` çağrılır.
    """
    ensure_ready(provider)
    fn = {"claude": _claude, "gemini": _gemini, "ollama": _ollama}[provider]
    backups = [fallback] if isinstance(fallback, str) else list(fallback or [])
    models = [model] + [m for m in dict.fromkeys(backups) if m and m != model]
    for i, m in enumerate(models):
        got_text = False
        try:
            for part in fn(system, user, m, temperature, max_tokens):
                if part:
                    got_text = True
                    yield part
        except LLMError:
            raise
        except Exception as e:
            if not got_text and _is_transient(e) and i + 1 < len(models):
                print(f"[bilgi] {m} geçici hata ({type(e).__name__}); yedek modele geçiliyor: {models[i + 1]}")
                if on_fallback:
                    on_fallback(m, models[i + 1])
                continue
            raise _friendly(e, provider, m) from None
        if not got_text:
            raise LLMError("Model boş bir cevap döndürdü. config.yaml içindeki max_tokens değerini artırıp tekrar deneyin.")
        return


def generate(system: str, user: str, provider: str, model: str, **kwargs) -> str:
    """Cevabın tamamını tek seferde döndürür (stream ile aynı seçenekler)."""
    return "".join(stream(system, user, provider, model, **kwargs))


# ---------------- Sağlayıcılar ----------------

def _claude(system, user, model, temperature, max_tokens):
    import anthropic

    client = anthropic.Anthropic(api_key=_key("claude"))
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as s:
        yield from s.text_stream


def _gemini(system, user, model, temperature, max_tokens):
    from google import genai
    from google.genai import types

    # Zaman aşımı (ms): yoğun anlarda istek sonsuza kadar beklemesin
    client = genai.Client(api_key=_key("gemini"), http_options=types.HttpOptions(timeout=60_000))
    for chunk in client.models.generate_content_stream(
        model=model,
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    ):
        yield chunk.text or ""


def _ollama(system, user, model, temperature, max_tokens):
    host = (get_secret("OLLAMA_HOST") or "http://localhost:11434").rstrip("/")
    payload = {
        "model": model,
        "stream": True,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    try:
        with httpx.stream("POST", f"{host}/api/chat", json=payload, timeout=300) as r:
            if r.status_code == 404:
                raise LLMError(f"“{model}” modeli Ollama'da yüklü değil. Önce şu komutu çalıştırın: ollama pull {model}")
            if r.status_code != 200:
                raise LLMError(f"Ollama bir hata döndürdü (kod {r.status_code}). Ollama penceresindeki kayıtlara göz atın.")
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                yield data.get("message", {}).get("content", "")
                if data.get("done"):
                    break
    except httpx.ConnectError:
        raise LLMError(f"Ollama'ya bağlanılamadı ({host}). Ollama uygulamasının açık olduğundan emin olun.") from None
