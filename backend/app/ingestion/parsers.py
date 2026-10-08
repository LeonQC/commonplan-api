from io import BytesIO
import re
from typing import Protocol

from pypdf import PdfReader

from app.ingestion.types import ParsedDocument, ParsedPage


class UnsupportedDocumentType(ValueError):
    pass


class DocumentParser(Protocol):
    name: str
    version: str

    def parse(self, content: bytes) -> ParsedDocument: ...


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


class TextParser:
    name = "text"
    version = "1"

    def parse(self, content: bytes) -> ParsedDocument:
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


class PdfParser:
    name = "pypdf"
    version = "1"

    def parse(self, content: bytes) -> ParsedDocument:
        reader = PdfReader(BytesIO(content))
        pages = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(ParsedPage(index, text, text))
        return ParsedDocument(self.name, self.version, pages)


class ParserRegistry:
    def __init__(self) -> None:
        text = TextParser()
        self._parsers: dict[str, DocumentParser] = {
            "text/plain": text,
            "text/markdown": text,
            "text/csv": text,
            "application/json": text,
            "application/pdf": PdfParser(),
        }

    def parse(self, content_type: str, content: bytes) -> ParsedDocument:
        parser = self._parsers.get(content_type)
        if parser is None:
            raise UnsupportedDocumentType(f"No ingestion parser for {content_type}")
        document = parser.parse(content)
        if not document.pages:
            raise ValueError("Document contains no extractable text")
        return document
