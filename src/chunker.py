"""tree-sitter ile Python dosyalarını fonksiyon/sınıf bazlı parçalara (chunk) böler.

Kurallar:
- Üst düzey fonksiyon      -> 1 chunk (kind="function")
- Sınıf                    -> sınıf başlığı 1 chunk (kind="class") + her metot ayrı chunk (kind="method")
- Bunların dışında kalan kod (import, sabitler vb.) -> kind="module" chunk
- Çok uzun parçalar max_chunk_lines satırlık dilimlere bölünür
"""
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
_parser = Parser(PY_LANGUAGE)


@dataclass
class Chunk:
    code: str          # kod metni
    file_path: str     # repo köküne göre göreli yol
    start_line: int    # 1'den başlar
    end_line: int      # dahil
    name: str          # fonksiyon/sınıf adı (metotlarda Sinif.metot)
    kind: str          # function | class | method | module

    @property
    def id(self) -> str:
        """Chunk için kararlı ve benzersiz kimlik."""
        key = f"{self.file_path}:{self.start_line}-{self.end_line}:{self.kind}:{self.name}"
        return hashlib.md5(key.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


def _definition(node):
    """Dekoratörlü tanımlarda (@property vb.) içteki asıl tanımı döndürür."""
    if node.type == "decorated_definition":
        return node.child_by_field_name("definition")
    return node


def _name_of(node) -> str:
    name = _definition(node).child_by_field_name("name")
    return name.text.decode("utf-8") if name else "<adsız>"


def _is_def(node) -> bool:
    return _definition(node).type in ("function_definition", "class_definition")


def _lines(node) -> tuple[int, int]:
    """Düğümün 1 tabanlı başlangıç ve bitiş satırı."""
    return node.start_point[0] + 1, node.end_point[0] + 1


def _make(lines, rel, start, end, name, kind, max_lines) -> list[Chunk]:
    """Satır aralığından chunk üretir; çok uzunsa dilimler."""
    out = []
    total = end - start + 1
    parts = (total + max_lines - 1) // max_lines
    for i in range(parts):
        s = start + i * max_lines
        e = min(end, s + max_lines - 1)
        part_name = name if parts == 1 else f"{name} (parça {i + 1}/{parts})"
        code = "\n".join(lines[s - 1:e])
        out.append(Chunk(code, rel, s, e, part_name, kind))
    return out


def chunk_file(path: Path, repo_root: Path, max_lines: int = 200) -> list[Chunk]:
    """Tek bir Python dosyasını chunk listesine çevirir."""
    source = path.read_bytes()
    text = source.decode("utf-8", errors="replace")
    lines = text.splitlines()
    rel = path.relative_to(repo_root).as_posix()
    tree = _parser.parse(source)

    chunks: list[Chunk] = []
    covered: set[int] = set()  # fonksiyon/sınıflara ait satırlar

    for node in tree.root_node.children:
        if not _is_def(node):
            continue
        start, end = _lines(node)
        covered.update(range(start, end + 1))
        name = _name_of(node)
        inner = _definition(node)

        if inner.type == "function_definition":
            chunks += _make(lines, rel, start, end, name, "function", max_lines)
            continue

        # --- Sınıf: metotları ayrı chunk yap, kalanı sınıf başlığı olsun ---
        body = inner.child_by_field_name("body")
        methods = [c for c in body.children if _is_def(c)] if body else []
        method_lines: set[int] = set()
        for m in methods:
            ms, me = _lines(m)
            method_lines.update(range(ms, me + 1))
            kind = "method" if _definition(m).type == "function_definition" else "class"
            chunks += _make(lines, rel, ms, me, f"{name}.{_name_of(m)}", kind, max_lines)

        # Sınıf başlığı: imza + docstring + sınıf değişkenleri (metotlar hariç)
        header = [ln for ln in range(start, end + 1) if ln not in method_lines]
        header_code = "\n".join(lines[ln - 1] for ln in header if lines[ln - 1].strip())
        if methods:
            # dict.fromkeys: sırayı koruyarak tekrarları (ör. @overload) temizler
            names = ", ".join(dict.fromkeys(_name_of(m) for m in methods))
            header_code += f"\n    # metotlar: {names}"
        chunks.append(Chunk(header_code, rel, start, end, name, "class"))

    # --- Fonksiyon/sınıf dışında kalan modül kodu (import, sabitler...) ---
    block: list[int] = []

    def flush():
        if block:
            chunks.extend(_make(lines, rel, block[0], block[-1], "<modül>", "module", max_lines))
            block.clear()

    for ln in range(1, len(lines) + 1):
        if ln in covered:
            flush()
        elif lines[ln - 1].strip():
            block.append(ln)
    flush()

    return sorted(chunks, key=lambda c: (c.start_line, c.kind != "class"))
