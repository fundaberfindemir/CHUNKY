"""Arayüz için HTML yardımcıları (Streamlit'ten bağımsız, test edilebilir).

Güvenlik: Repodan gelen her metin (dosya yolu, ad, kod) html.escape veya
Pygments ile kaçışlanır; böylece kötü niyetli bir repo sayfaya HTML/JS sokamaz.
Stiller assets/style.css içindedir; burada sadece yapı (HTML) üretilir.
"""
import re
from html import escape
from pathlib import Path
from urllib.parse import quote

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

_LEXER = PythonLexer()
KIND_TR = {"function": "fonksiyon", "method": "metot", "class": "sınıf", "module": "modül"}

# ---------------- Simgeler (satır içi SVG, dış bağımlılık yok) ----------------
_P = {
    "diamond": '<path d="M12 2.5 21.5 12 12 21.5 2.5 12Z"/><path d="M12 7.5 16.5 12 12 16.5 7.5 12Z"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7.5a4 4 0 0 1 8 0V11"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9.5 9.5h5v5h-5zM9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "cloud": '<path d="M7 19a5 5 0 0 1-.6-9.96A6.5 6.5 0 0 1 19 10.5a4.25 4.25 0 0 1-.75 8.5Z"/>',
    "file": '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z"/><path d="M14 3v5h5"/>',
    "fn": '<path d="M9 20c2 0 2.5-1.5 3-4l1.5-8c.5-2.5 1-4 3-4"/><path d="M8 11h8"/>',
    "box": '<path d="M21 8 12 3 3 8v8l9 5 9-5Z"/><path d="m3 8 9 5 9-5M12 13v8"/>',
    "dot": '<circle cx="12" cy="12" r="3.5"/><circle cx="12" cy="12" r="9"/>',
    "layers": '<path d="m12 3 9 5-9 5-9-5Z"/><path d="m3 13 9 5 9-5"/>',
    "alert": '<path d="M10.3 4.2 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9.5v4M12 17h.01"/>',
    "key": '<circle cx="8" cy="15" r="4.5"/><path d="m11.2 11.8 8.8-8.8M16 7l3 3M14 9l2 2"/>',
    "check-circle": '<circle cx="12" cy="12" r="9"/><path d="m8 12.5 2.7 2.7L16 9.8"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
    "chevron": '<path d="m9 6 6 6-6 6"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
}


def icon(name: str) -> str:
    """Simge: HTML'de sadece bir <span>; çizim CSS maskesiyle yapılır.
    (Streamlit'in HTML temizleyicisi satır içi <svg>'yi siler, bu yöntem etkilenmez.)"""
    return f'<span class="ic ic-{name}" aria-hidden="true"></span>'


def _icons_css() -> str:
    """Her simge için URL-kodlu SVG maskesi üretir (metinde '<' kalmaz)."""
    rules = []
    for name, paths in _P.items():
        svg = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' "
               f"stroke-width='1.7' stroke-linecap='round' stroke-linejoin='round'>{paths.replace(chr(34), chr(39))}</svg>")
        rules.append(f'.ic-{name}{{--ic:url("data:image/svg+xml,{quote(svg, safe=" =:/,.-_")}")}}')
    return "\n".join(rules)


# ---------------- Sayfa düzeyi ----------------
def load_css(path: Path) -> str:
    """CSS dosyası + simge maskeleri. Not: Streamlit içinde '<' geçen <style> bloklarını
    güvenlik gereği siler; bu yüzden CSS'te '<' yerine \\3C kullanılır."""
    css = path.read_text(encoding="utf-8") + "\n" + _icons_css()
    assert "<" not in css, "CSS içinde '<' karakteri olmamalı"
    return f"<style>{css}</style>"


def theme_flag(theme: str) -> str:
    """Açık temada CSS'in :root:has(#chunky-light) kuralını tetikleyen işaret."""
    return '<div id="chunky-light"></div>' if theme == "light" else ""


# Kopyala düğmesi için tek seferlik, küçük ve yerel script (event delegation)
COPY_JS = """
<div class="chunky-js"></div>
<script>
(() => {
  const doc = window.parent?.document || document;
  if (doc.__chunkyCopy) return;
  doc.__chunkyCopy = true;
  doc.addEventListener("click", async (ev) => {
    // Cevaptaki kaynak rozeti: ilgili kartı aç, yumuşakça kaydır, kısa süre vurgula
    const chip = ev.target.closest('a[href^="#src-"]');
    if (chip) {
      ev.preventDefault(); ev.stopPropagation();
      const card = doc.getElementById(chip.getAttribute("href").slice(1));
      if (!card) return;
      card.open = true;
      card.scrollIntoView({ behavior: "smooth", block: "center" });
      card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
      return;
    }
    const btn = ev.target.closest(".copy-btn");
    if (!btn) return;
    ev.preventDefault(); ev.stopPropagation();
    const raw = btn.closest(".src")?.querySelector("textarea.raw");
    if (!raw) return;
    try { await navigator.clipboard.writeText(raw.value); }
    catch (_) { raw.style.display = "block"; raw.select(); doc.execCommand("copy"); raw.style.display = ""; }
    const label = btn.querySelector(".lbl");
    btn.classList.add("done"); label.textContent = "Kopyalandı";
    setTimeout(() => { btn.classList.remove("done"); label.textContent = "Kopyala"; }, 1600);
  }, true);
})();
</script>"""


# ---------------- Kenar çubuğu ----------------
def brand() -> str:
    return f"""<div class="brand"><div class="brand-mark">{icon("diamond")}</div>
<div><div class="brand-name">Chunky</div><div class="brand-sub">Kod · Sohbet</div></div></div>"""


def side_title(text: str) -> str:
    return f'<div class="side-title">{escape(text)}</div>'


def key_pill(state: str, text: str) -> str:
    """state: ok | no | local"""
    return f'<div class="key-pill {state}"><span class="dot"></span><span>{escape(text)}</span></div>'


# ---------------- Hero ve istatistikler ----------------
def hero(repo: str | None, provider_name: str, model: str, is_local: bool) -> str:
    if is_local:
        privacy = f'<span class="badge local">{icon("cpu")}<b>Yerel</b> · Kodunuz bilgisayarınızdan çıkmaz</span>'
    else:
        privacy = (f'<span class="badge cloud">{icon("cloud")}<b>Bulut</b> · '
                   f'Soru ve ilgili kod parçaları {escape(provider_name)}’e gönderilir</span>')
    keys = f'<span class="badge neutral">{icon("lock")}Anahtarlar ekranda gösterilmez</span>'
    meta = ""
    if repo:
        meta = (f'<div class="meta"><span>repo <code>{escape(repo)}</code></span>'
                f'<span>model <code>{escape(model)}</code></span></div>')
    return f"""<div class="hero">
  <div class="eyebrow">Kod tabanıyla sohbet</div>
  <h1>Kodunuzla <em>konuşun.</em></h1>
  <p class="lede">Bir Python reposuna soru sorun; cevaplar ilgili fonksiyon, dosya yolu ve satır numarasıyla gelsin.</p>
  <div class="badges">{privacy}{keys}</div>{meta}
</div>"""


def stats(d: dict) -> str:
    items = [("Dosya", d["files"], "file"), ("Fonksiyon", d["function"], "fn"),
             ("Sınıf", d["class"], "box"), ("Metot", d["method"], "dot")]
    cards = "".join(
        f'<div class="stat"><div class="stat-top"><span class="lbl">{l}</span>{icon(ic)}</div>'
        f'<div class="num" style="--to:{int(n)}" aria-label="{int(n)}"></div></div>'
        for l, n, ic in items)
    return f'<div class="stats">{cards}</div>'


def section_head(title: str, note: str = "") -> str:
    return f'<div class="section-head"><h3>{escape(title)}</h3><span>{escape(note)}</span></div>'


def suggestion(ic: str, title: str, desc: str, delay_ms: int = 0) -> str:
    return (f'<div class="sug" style="animation-delay:{delay_ms}ms"><div class="sug-icon">{icon(ic)}</div>'
            f'<div><div class="sug-title">{escape(title)}</div><div class="sug-desc">{escape(desc)}</div></div>'
            f'<div class="sug-arrow">{icon("arrow")}</div></div>')


# ---------------- Bildirim ve ilerleme ----------------
_NOTICE_ICON = {"info": "info", "ok": "check-circle", "warn": "alert", "err": "alert"}


def notice(kind: str, title: str, body: str = "") -> str:
    """kind: info | ok | warn | err"""
    b = f'<div class="notice-body">{escape(body)}</div>' if body else ""
    return (f'<div class="notice {kind}" role="status">{icon(_NOTICE_ICON[kind])}'
            f'<div><div class="notice-title">{escape(title)}</div>{b}</div></div>')


INDEX_STEPS = ["Repo indiriliyor", "Dosyalar okunuyor", "Parçalanıyor", "İndeksleniyor"]


def progress(step: int, frac: float, detail: str = "") -> str:
    """İndeksleme adımlarını ve toplam ilerlemeyi gösterir."""
    total = int(min(1.0, (step + frac) / len(INDEX_STEPS)) * 100)
    rows = []
    for i, name in enumerate(INDEX_STEPS):
        state = "done" if i < step else "active" if i == step else ""
        mark = icon("check") if state == "done" else ""
        extra = f"<em>{escape(detail)}</em>" if state == "active" and detail else ""
        rows.append(f'<li class="{state}"><span class="st">{mark}</span>{name}{extra}</li>')
    return (f'<div class="prog"><div class="prog-top"><span class="prog-title">İndeksleniyor</span>'
            f'<span class="prog-pct">%{total}</span></div><div class="prog-bar"><i style="width:{total}%"></i></div>'
            f'<ol>{"".join(rows)}</ol></div>')


def typing(text: str = "Kod aranıyor") -> str:
    return f'<div class="typing"><i></i><i></i><i></i><span>{escape(text)}…</span></div>'


# ---------------- Kaynak kartları ----------------
def code_html(code: str, start_line: int) -> str:
    """Kodu, dosyadaki GERÇEK satır numaralarıyla renklendirir."""
    fmt = HtmlFormatter(linenos="inline", linenostart=start_line, cssclass="cx", nobackground=True)
    return highlight(code, _LEXER, fmt)


def source_card(msg_id: int, k: int, s: dict) -> str:
    """Varsayılan kapalı, tıklayınca açılan kaynak kartı."""
    # Skor yalnızca anlam eşleşmesinde vardır; sadece kelimeyle bulunanlarda "—" gösterilir
    score = s.get("score")
    pct = max(0, min(100, int(round(score * 100)))) if score is not None else 0
    score_txt = f"{score:.2f}" if score is not None else "—"
    match = s.get("match", "")
    match_cls = {"anlam + kelime": "both", "anlam": "dense", "kelime": "sparse"}.get(match, "dense")
    match_tip = {"both": "Hem anlam hem kelime aramasında bulundu",
                 "dense": "Anlam (vektör) aramasında bulundu",
                 "sparse": "Kelime (BM25) aramasında bulundu"}[match_cls]
    match_html = f'<span class="src-match {match_cls}" title="{match_tip}">{escape(match)}</span>' if match else ""
    kind = KIND_TR.get(s["kind"], s["kind"])
    path = s["file_path"]
    folder, _, fname = path.rpartition("/")
    path_html = (escape(folder + "/") if folder else "") + f"<b>{escape(fname)}</b>"
    lines = f'{s["start_line"]}–{s["end_line"]}'
    return f"""<details class="src" id="src-{msg_id}-{k}">
<summary>
  <span class="src-idx">{k}</span>
  <span class="src-main"><span class="src-name">{escape(s["name"])}</span>
    <span class="src-path">{path_html} · satır {lines}</span></span>
  <span class="src-side"><span class="src-kind">{escape(kind)}</span>
    {match_html}
    <span class="src-score" title="Anlam benzerliği"><span class="src-bar"><i style="width:{pct}%"></i></span>{score_txt}</span>
    <span class="src-chev">{icon("chevron")}</span></span>
</summary>
<div class="code">
  <div class="code-head"><span class="code-file">{icon("file")}{escape(fname)}<span>:{lines}</span></span>
    <button class="copy-btn" type="button" aria-label="Kodu kopyala">{icon("copy")}<span class="lbl">Kopyala</span></button></div>
  {code_html(s["code"], s["start_line"])}
  <textarea class="raw" aria-hidden="true" tabindex="-1">{escape(s["code"])}</textarea>
</div>
</details>"""


def sources_block(msg_id: int, sources: list[dict]) -> str:
    cards = "".join(source_card(msg_id, k, s) for k, s in enumerate(sources, 1))
    return (f'<div class="sources"><div class="sources-head">Kaynaklar · <b>{len(sources)}</b> kod parçası</div>'
            f'{cards}</div>')


# ---------------- Cevaptaki dosya:satır atıflarını rozete çevirme ----------------
_CITE = re.compile(r"`?((?:[\w.\-]+/)*[\w.\-]+\.py):(\d+)(?:\s*[-–]\s*(\d+))?`?")


def _match_source(path: str, a: int, b: int, sources: list[dict]) -> int | None:
    """Atıfa en uygun kaynak kartının numarası (yol + satır çakışması)."""
    best = None
    for k, s in enumerate(sources, 1):
        if not (s["file_path"] == path or s["file_path"].endswith("/" + path)):
            continue
        if a <= s["end_line"] and b >= s["start_line"]:
            return k
        best = best or k
    return best


def linkify(text: str, sources: list[dict], msg_id: int) -> str:
    """`dosya.py:10-20` biçimindeki atıfları tıklanabilir rozet bağlantılarına çevirir.
    Kod blokları (```) içine dokunmaz."""
    parts = re.split(r"(```.*?```)", text, flags=re.S)
    for i, part in enumerate(parts):
        if part.startswith("```"):
            continue

        def repl(m):
            path, a = m.group(1), int(m.group(2))
            b = int(m.group(3) or a)
            k = _match_source(path, a, b, sources)
            short = path.rsplit("/", 1)[-1]
            label = f"{short}:{a}" + (f"–{b}" if b != a else "")
            label = label.replace("_", r"\_")  # markdown vurgusunu engelle
            return f"[{label}](#src-{msg_id}-{k})" if k else f"`{m.group(0).strip('`')}`"

        parts[i] = _CITE.sub(repl, part)
    return "".join(parts)
