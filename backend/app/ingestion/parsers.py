from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import PurePath
import re
from typing import Protocol

from app.config import settings
from app.ingestion.types import ParsedDocument, ParsedPage


class UnsupportedDocumentType(ValueError):
    pass


class DocumentParser(Protocol):
    name: str
    version: str

    def parse(self, content: bytes, filename: str) -> ParsedDocument: ...


def _decode(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("utf-8", errors="replace")


def _heading(text: str) -> str | None:
    headings = [
        match.group(2).strip()
        for match in re.finditer(r"^(#{1,6})\s+(.+?)\s*$", text, flags=re.MULTILINE)
    ]
    return " > ".join(headings[-3:]) if headings else None


def _plain_text(markdown: str) -> str:
    """Keep table cell text while removing the most common Markdown markup."""
    text = re.sub(r"!\[[^]]*]\([^)]*\)", " ", markdown)
    text = re.sub(r"\[([^]]+)]\([^)]*\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[`*_~]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


class TextParser:
    name = "text"
    version = "1"

    def parse(self, content: bytes, filename: str = "document.txt") -> ParsedDocument:
        sections = _decode(content).split("\f")
        pages = [
            ParsedPage(
                page_number=index,
                markdown_content=section.strip(),
                plain_text=section.strip(),
                heading_path=_heading(section),
            )
            for index, section in enumerate(sections, start=1)
            if section.strip()
        ]
        return ParsedDocument(self.name, self.version, pages)


class DoclingParser:
    name = "docling"

    def __init__(self, converter=None) -> None:
        self._converter = converter
        try:
            self.version = version("docling")
        except PackageNotFoundError:
            self.version = "unavailable"

    def _get_converter(self):
        if self._converter is None:
            try:
                from docling.document_converter import DocumentConverter
            except ImportError as exc:
                raise RuntimeError(
                    "Docling is required by the ingestion worker image"
                ) from exc
            self._converter = DocumentConverter()
        return self._converter

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        try:
            from docling.datamodel.base_models import DocumentStream
            from docling.exceptions import ConversionError
        except ImportError as exc:
            raise RuntimeError("Docling is required by the ingestion worker image") from exc

        try:
            result = self._get_converter().convert(
                DocumentStream(name=filename, stream=BytesIO(content)),
                max_num_pages=settings.ingestion_docling_max_pages,
                max_file_size=settings.attachment_upload_max_bytes,
            )
        except ConversionError as exc:
            # Malformed/unsupported file contents will not improve on retry.
            raise ValueError(f"Docling could not convert {filename}") from exc
        document = result.document
        page_numbers = sorted(getattr(document, "pages", {}).keys())
        pages: list[ParsedPage] = []
        if page_numbers:
            for page_number in page_numbers:
                markdown = document.export_to_markdown(page_no=page_number).strip()
                if markdown:
                    pages.append(ParsedPage(
                        page_number=page_number,
                        markdown_content=markdown,
                        plain_text=_plain_text(markdown),
                        heading_path=_heading(markdown),
                    ))
        else:
            markdown = document.export_to_markdown().strip()
            if markdown:
                pages.append(ParsedPage(
                    page_number=1,
                    markdown_content=markdown,
                    plain_text=_plain_text(markdown),
                    heading_path=_heading(markdown),
                ))
        return ParsedDocument(self.name, self.version, pages, native_document=document)


_CONTENT_TYPE_SUFFIXES = {
    "application/pdf": ".pdf",
    "text/csv": ".csv",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
}


class ParserRegistry:
    def __init__(self, docling: DocumentParser | None = None) -> None:
        text = TextParser()
        docling = docling or DoclingParser()
        self._parsers: dict[str, DocumentParser] = {
            "text/plain": text,
            "text/markdown": text,
            "application/json": text,
            "application/pdf": docling,
            "text/csv": docling,
            "image/gif": docling,
            "image/jpeg": docling,
            "image/png": docling,
            "image/webp": docling,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": docling,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": docling,
            "application/vnd.openxmlformats-officedocument.presentationml.presentation": docling,
        }

    def parse(self, content_type: str, content: bytes, filename: str) -> ParsedDocument:
        parser = self._parsers.get(content_type)
        if parser is None:
            raise UnsupportedDocumentType(f"No ingestion parser for {content_type}")
        if not PurePath(filename).suffix:
            filename = f"document{_CONTENT_TYPE_SUFFIXES.get(content_type, '')}"
        document = parser.parse(content, filename)
        if not document.pages:
            raise ValueError("Document contains no extractable text")
        return document
