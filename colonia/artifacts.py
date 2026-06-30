from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from colonia.models import ArtifactRecord


ARTIFACT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".html",
    ".ipynb",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".txt",
    ".xls",
    ".xlsx",
    ".zip",
}

CODE_LANGUAGE_EXTENSIONS = {
    "bash": ".sh",
    "c": ".c",
    "cpp": ".cpp",
    "css": ".css",
    "go": ".go",
    "html": ".html",
    "java": ".java",
    "javascript": ".js",
    "js": ".js",
    "json": ".json",
    "jsx": ".jsx",
    "markdown": ".md",
    "md": ".md",
    "py": ".py",
    "python": ".py",
    "rust": ".rs",
    "rs": ".rs",
    "sh": ".sh",
    "sql": ".sql",
    "tsx": ".tsx",
    "typescript": ".ts",
    "ts": ".ts",
    "yaml": ".yaml",
    "yml": ".yml",
}

FENCED_CODE_RE = re.compile(
    r"```(?P<lang>[A-Za-z0-9_+.-]*)[^\n]*\n(?P<code>.*?)(?:\n)?```",
    flags=re.DOTALL,
)

_LINK_SCRAPE_JS = """() => Array.from(document.querySelectorAll('a[href]')).map((a) => ({
    href: a.href,
    text: (a.innerText || a.textContent || '').trim(),
    download: a.getAttribute('download') || '',
}))"""


def collect_page_artifacts(
    page,
    *,
    artifact_root: Path,
    browser: str,
    service: str,
) -> list[ArtifactRecord]:
    records: list[ArtifactRecord] = []
    target_dir = artifact_root / browser / service
    seen: set[str] = set()

    for link in _page_links(page):
        url = str(link.get("href") or "")
        if not url or url in seen:
            continue
        seen.add(url)
        if not _looks_like_artifact(
            url, str(link.get("download") or ""), str(link.get("text") or "")
        ):
            continue

        record = _download_link_artifact(page, url, link, target_dir)
        if record:
            records.append(record)

    return records


def collect_code_artifacts(
    text: str,
    *,
    artifact_root: Path,
    browser: str,
    service: str,
) -> list[ArtifactRecord]:
    records: list[ArtifactRecord] = []
    target_dir = artifact_root / browser / service / "code"
    for index, match in enumerate(FENCED_CODE_RE.finditer(text or ""), 1):
        code = match.group("code").rstrip()
        if not code.strip():
            continue
        lang = (match.group("lang") or "").lower()
        suffix = CODE_LANGUAGE_EXTENSIONS.get(lang, ".txt")
        target_dir.mkdir(parents=True, exist_ok=True)
        path = _unique_path(target_dir / f"code-block-{index:02d}{suffix}")
        content = code + "\n"
        path.write_text(content, encoding="utf-8")
        records.append(
            ArtifactRecord(
                source="code_block",
                name=path.name,
                path=str(path),
                mime_type=_code_mime_type(suffix),
                size_bytes=len(content.encode("utf-8")),
            )
        )
    return records


def _page_links(page) -> list[dict[str, str]]:
    try:
        links = page.evaluate(_LINK_SCRAPE_JS)
    except Exception:
        return []
    return links if isinstance(links, list) else []


def _looks_like_artifact(url: str, download: str, text: str) -> bool:
    if download.strip():
        return True
    candidates = [urlparse(url).path, urlparse(url).query, text]
    return any(_extension_from_name(candidate) in ARTIFACT_EXTENSIONS for candidate in candidates)


def _download_link_artifact(
    page,
    url: str,
    link: dict[str, str],
    target_dir: Path,
) -> ArtifactRecord | None:
    try:
        response = page.context.request.get(url, timeout=30_000)
        if not getattr(response, "ok", False):
            return None
        body = response.body()
    except Exception:
        return None

    headers = {str(k).lower(): str(v) for k, v in getattr(response, "headers", {}).items()}
    filename = _filename_for_link(url, link, headers)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = _unique_path(target_dir / filename)
    path.write_bytes(body)

    return ArtifactRecord(
        source="link",
        name=path.name,
        path=str(path),
        url=url,
        mime_type=headers.get("content-type"),
        size_bytes=len(body),
    )


def _filename_for_link(url: str, link: dict[str, str], headers: dict[str, str]) -> str:
    disposition_name = _filename_from_content_disposition(headers.get("content-disposition", ""))
    for candidate in (
        disposition_name,
        str(link.get("download") or ""),
        Path(unquote(urlparse(url).path)).name,
        str(link.get("text") or ""),
    ):
        safe = _safe_filename(candidate)
        if safe:
            return safe
    return "artifact.bin"


def _filename_from_content_disposition(value: str) -> str:
    match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', value, flags=re.IGNORECASE)
    return unquote(match.group(1)) if match else ""


def _safe_filename(name: str) -> str:
    name = Path(name.strip()).name
    if not name or name in {".", ".."}:
        return ""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    return cleaned[:160]


def _extension_from_name(name: str) -> str:
    return Path(unquote(name).split("?", 1)[0]).suffix.lower()


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def _code_mime_type(suffix: str) -> str:
    if suffix == ".json":
        return "application/json"
    if suffix in {".html", ".css", ".md"}:
        return f"text/{suffix.removeprefix('.')}"
    return "text/plain"
