from __future__ import annotations

import gc
from pathlib import Path

from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.document_converter import DocumentConverter

# Params: edit these, then run `uv run --project backend data/convert.py`
DATA_DIR = Path(__file__).resolve().parent
INPUT_DIR = DATA_DIR / "downloads"
OUTPUT_DIR = DATA_DIR / "markdown"
INPUT_SUFFIXES = (".htm", ".html", ".xhtml")
SKIP_EXISTING = True


def html_files() -> list[Path]:
    files = [
        path
        for path in INPUT_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in INPUT_SUFFIXES
    ]
    return sorted(files)


def output_path_for(source: Path) -> Path:
    """Mirror the downloads/ tree under markdown/, swapping the suffix for .md."""
    return (OUTPUT_DIR / source.relative_to(INPUT_DIR)).with_suffix(".md")


def convert_corpus() -> tuple[int, int, int]:
    converter = DocumentConverter(allowed_formats=[InputFormat.HTML])
    converted = skipped = failed = 0

    for source in html_files():
        destination = output_path_for(source)
        label = source.relative_to(INPUT_DIR).as_posix()

        if SKIP_EXISTING and destination.exists():
            print(f"Skipping {label} (already converted)")
            skipped += 1
            continue

        print(f"Converting {label}...")

        # Serializing a large filing can exhaust memory; keep going so one bad
        # file doesn't lose the rest of the run. Re-running retries it.
        try:
            markdown = convert_one(converter, source)
        except MemoryError:
            print("  FAILED: out of memory while converting")
            failed += 1
            continue

        if markdown is None:
            failed += 1
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(markdown, encoding="utf-8")
        converted += 1

    return converted, skipped, failed


def convert_one(converter: DocumentConverter, source: Path) -> str | None:
    """Return the filing as Markdown, or None if Docling could not parse it."""
    result = converter.convert(source, raises_on_error=False)

    if result.status is ConversionStatus.FAILURE:
        errors = "; ".join(error.error_message for error in result.errors)
        print(f"  FAILED: {errors or result.status.value}")
        return None

    if result.status is ConversionStatus.PARTIAL_SUCCESS:
        print("  Partial success — some content may be missing")

    markdown = result.document.export_to_markdown()
    del result
    gc.collect()
    return markdown


if __name__ == "__main__":
    converted, skipped, failed = convert_corpus()
    print(
        f"Converted {converted} file(s), skipped {skipped}, failed {failed} "
        f"→ {OUTPUT_DIR}"
    )
    raise SystemExit(1 if failed else 0)
