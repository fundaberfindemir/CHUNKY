"""Kod Tabanıyla Sohbet - Streamlit arayüzü.

Çalıştırma:  streamlit run app.py
Stiller: assets/style.css · HTML parçaları: src/ui.py
"""
from pathlib import Path

import streamlit as st

from src import ui
from src.config import load_config, resolve_path
from src.indexer import collection_name, get_client, index_repo, list_repos, repo_stats
from src.llm import DISPLAY_NAMES, KEY_NAMES, LOCAL_PROVIDERS, LLMError, has_key, key_looks_valid
from src.rag import answer_stream
from src.repo_loader import RepoError, clone_repo

st.set_page_config(page_title="Chunky · Kod Tabanıyla Sohbet", page_icon="◆", layout="wide")

# Boş ekrandaki örnek sorular: (simge, başlık, açıklama, soru)
SUGGESTIONS = [
    ("layers", "Mimariyi keşfet", "Ana sınıflar ve her birinin sorumluluğu",
     "Bu projenin ana sınıfları neler ve ne işe yarıyor?"),
    ("alert", "Hata yönetimi", "Özel hata sınıfları ve fırlatıldıkları yerler",
     "Hatalar nasıl ele alınıyor, hangi özel hata sınıfları var?"),
    ("key", "Güvenlik", "Gizli anahtarın nerede ve nasıl kullanıldığı",
     "Gizli anahtar (secret key) nasıl kullanılıyor?"),
    ("check-circle", "Testler", "Hangi davranışların test edildiği",
     "Testler hangi senaryoları kapsıyor?"),
]
USER_AVATAR, BOT_AVATAR = ":material/person:", ":material/diamond:"


@st.cache_resource
def _client():
    """ChromaDB istemcisi tek sefer oluşturulur."""
    return get_client(resolve_path(load_config(), "db_dir"))


cfg = load_config()
client = _client()
ss = st.session_state

# Bir önceki çalıştırmadan gelen istekler (widget'lar oluşmadan önce uygulanmalı)
if "next_repo" in ss:
    ss["repo"] = ss.pop("next_repo")

# ---------------- Kenar çubuğu ----------------
with st.sidebar:
    st.html(ui.brand())

    # Tema: tek tıkla geçiş, tercih oturumda hatırlanır
    theme = st.segmented_control(
        "Tema", ["dark", "light"], key="theme", default="dark", required=True, width="stretch",
        label_visibility="collapsed",
        format_func=lambda t: ":material/dark_mode: Koyu" if t == "dark" else ":material/light_mode: Açık",
    ) or "dark"

    st.html(ui.side_title("Model"))
    providers = list(KEY_NAMES)
    provider = st.selectbox(
        "Sağlayıcı", providers, index=providers.index(cfg["llm"]["provider"]),
        format_func=lambda p: f"{DISPLAY_NAMES[p]} · {'yerel' if p in LOCAL_PROVIDERS else 'bulut'}",
    )
    model = st.text_input("Model adı", value=cfg["llm"]["models"][provider], key=f"model-{provider}")

    # Anahtarın sadece VAR/YOK durumu gösterilir, değeri asla gösterilmez
    key_name = KEY_NAMES[provider]
    if not key_name:
        st.html(ui.key_pill("local", "Yerel model · anahtar gerekmez"))
    elif has_key(provider) and not key_looks_valid(provider):
        hint = "eksik ya da boşluklu görünüyor" if provider == "gemini" else "sk-ant- ile başlamalı"
        st.html(ui.key_pill("no", f"{key_name} {hint}"))
    elif has_key(provider):
        st.html(ui.key_pill("ok", f"{key_name} tanımlı"))
    else:
        st.html(ui.key_pill("no", f"{key_name} eksik · .env dosyasına ekleyin"))

    top_k = st.slider("Bağlam parçası", 1, 15, cfg["search"]["top_k"],
                      help="Cevap için modele gönderilecek en benzer kod parçası sayısı")

    st.html(ui.side_title("Repo"))
    repos = list_repos(client)
    repo = st.selectbox("Aktif repo", repos, key="repo") if repos else None

    with st.expander("Yeni repo indeksle", icon=":material/add:", expanded=not repos):
        url = st.text_input("GitHub adresi", placeholder="https://github.com/kisi/proje")
        go = st.button("Klonla ve indeksle", use_container_width=True, disabled=not url.strip())
        box = st.empty()
        if go:
            def show(step, frac, detail=""):
                box.html(ui.progress(step, frac, detail))
            try:
                show(0, 0.3, "GitHub")
                path = clone_repo(url, resolve_path(cfg, "repos_dir"))
                n = index_repo(path, cfg, client, progress=show)
                ss["flash"] = ("ok", "Repo hazır", f"{path.name} · {n} kod parçası indekslendi.")
                ss["next_repo"] = collection_name(path.name)
                st.rerun()
            except RepoError as e:
                box.html(ui.notice("err", "İndeksleme yapılamadı", str(e)))
            except Exception as e:  # beklenmeyen durumlarda ayrıntı sızdırmadan bilgi ver
                print(f"[hata] indeksleme: {type(e).__name__}")
                box.html(ui.notice("err", "Beklenmeyen bir sorun oluştu",
                                   "İndeksleme tamamlanamadı. Lütfen tekrar deneyin."))

    if repo and ss.get("history", {}).get(repo):
        if st.button("Sohbeti temizle", icon=":material/delete_sweep:", use_container_width=True):
            ss["history"].pop(repo, None)
            st.rerun()

# Stil, tema işareti ve kopyala script'i
st.html(ui.load_css(Path(__file__).parent / "assets" / "style.css"))
if theme == "light":
    st.html(ui.theme_flag(theme))
st.html(ui.COPY_JS, unsafe_allow_javascript=True)

# ---------------- Ana alan ----------------
st.html(ui.hero(repo, DISPLAY_NAMES[provider], model, provider in LOCAL_PROVIDERS))

if flash := ss.pop("flash", None):
    st.html(ui.notice(*flash))

if not repo:
    st.html(ui.notice("info", "Henüz indekslenmiş bir repo yok",
                      "Soldaki “Yeni repo indeksle” bölümüne bir GitHub adresi yazarak başlayın."))
    st.stop()

history = ss.setdefault("history", {}).setdefault(repo, [])


def render(msg: dict, i: int):
    """Geçmişteki bir mesajı çizer (i: mesajın sıra numarası, kaynak kimlikleri için)."""
    if msg["role"] == "user":
        with st.chat_message("user", avatar=USER_AVATAR):
            with st.container(key=f"umsg-{i}"):
                st.markdown(msg["content"])
        return
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        with st.container(key=f"amsg-{i}"):
            if msg.get("note"):
                st.html(ui.notice("warn", *msg["note"]))
            st.markdown(ui.linkify(msg["content"], msg["sources"], i))
            st.html(ui.sources_block(i, msg["sources"]))


# Boş sohbet: istatistikler + örnek soru kartları
pending = ss.pop("pending", None)
if not history and not pending:
    st.html(ui.stats(repo_stats(client, repo)))
    st.html(ui.section_head("Şununla başlayabilirsiniz", "Bir karta tıklayın ya da kendi sorunuzu yazın"))
    cols = st.columns(2, gap="small")
    for i, (ic, title, desc, q) in enumerate(SUGGESTIONS):
        with cols[i % 2], st.container(key=f"sugcard-{i}"):
            st.html(ui.suggestion(ic, title, desc, delay_ms=80 * i))
            if st.button(title, key=f"sugask-{i}"):
                ss["pending"] = q
                st.rerun()

for i, msg in enumerate(history):
    render(msg, i)

question = st.chat_input(f"{repo} hakkında bir soru sorun…") or pending
if question:
    history.append({"role": "user", "content": question})
    render(history[-1], len(history) - 1)

    mid = len(history)  # yeni asistan mesajının sıra numarası
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        with st.container(key=f"amsg-{mid}"):
            note_box = st.empty()  # yedek modele geçilirse bilgi notu
            out = st.empty()
            out.html(ui.typing("Kod aranıyor"))
            text = ""

            busy = []  # yoğun çıkan modeller (birden fazla olabilir)

            def fallback_note(main_model, backup_model):
                """Asıl model yoğunsa kullanıcıya bilgi ver; not geçmişte de saklanır."""
                busy.append(main_model)
                note_text = (f"{', '.join(busy)} şu an yoğun",
                             f"Bu cevap yedek model {backup_model} ile hazırlandı.")
                note_box.html(ui.notice("warn", *note_text))
                out.html(ui.typing("Yedek modelle deneniyor"))
                fallback_note.result = note_text

            fallback_note.result = None
            try:
                hits, chunks = answer_stream(question, repo, cfg, client, provider, model, top_k,
                                             on_fallback=fallback_note)
                out.html(ui.typing("Cevap yazılıyor"))
                # Akan yazı: her parçada metni güncelle, sonunda imleç yanıp söner
                with st.container(key="streaming"):
                    live = st.empty()
                    for part in chunks:
                        text += part
                        out.empty()
                        live.markdown(ui.linkify(text, hits, mid))
                live.empty()
                st.markdown(ui.linkify(text, hits, mid))
                st.html(ui.sources_block(mid, hits))
                history.append({"role": "assistant", "content": text, "sources": hits,
                                "note": fallback_note.result})
            except LLMError as e:
                out.html(ui.notice("err", "Cevap alınamadı", str(e)))
                history.pop()  # cevapsız soruyu geçmişe yazma
