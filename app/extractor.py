from html.parser import HTMLParser
from pathlib import Path
import posixpath
import xml.etree.ElementTree as ET
from urllib.parse import unquote
import zipfile
from .text_cleaner import clean_pdf_pages

CHAPTER_MARKER = '\n\n=== CHAPTER BREAK ===\n\n'


class ParagraphParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if not self.hidden and tag in ('p', 'div', 'h1', 'h2', 'h3', 'li', 'br'):
            self.parts.append('\n\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in ('p', 'div', 'h1', 'h2', 'h3', 'li'):
            self.parts.append('\n\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract(path):
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == '.txt':
        return path.read_text(encoding='utf-8-sig').strip()
    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError('PDF extraction needs pypdf. Run the launcher to install dependencies.') from exc
        reader = PdfReader(path)
        if reader.is_encrypted and not reader.decrypt(''):
            raise ValueError('PDF is password protected; provide an unlocked copy.')
        pages = [page.extract_text(extraction_mode='layout', layout_mode_strip_rotated=False) or ''
                 for page in reader.pages]
        empty = [i + 1 for i, page in enumerate(pages) if not page.strip()]
        if empty:
            raise ValueError(f'PDF pages {empty} have no extractable text. They may be scanned or blank. '
                             'Use an OCR tool to create a searchable copy, then import that copy.')
        return clean_pdf_pages(pages)
    if suffix == '.epub':
        with zipfile.ZipFile(path) as book:
            container = ET.fromstring(book.read('META-INF/container.xml'))
            package_path = next(e.attrib['full-path'] for e in container.iter() if e.tag.endswith('rootfile'))
            package = ET.fromstring(book.read(package_path))
            items = {e.attrib['id']: e.attrib for e in package.iter() if e.tag.endswith('}item')}
            chapters = []
            for reference in package.iter():
                if not reference.tag.endswith('}itemref') or reference.attrib.get('linear') == 'no':
                    continue
                item = items[reference.attrib['idref']]
                if item.get('media-type') not in ('application/xhtml+xml', 'text/html'):
                    continue
                name = posixpath.normpath(posixpath.join(posixpath.dirname(package_path), unquote(item['href'].split('#')[0])))
                parser = ParagraphParser()
                parser.feed(book.read(name).decode('utf-8-sig'))
                import re
                text = re.sub(r'\n\s*\n', '\n\n', ''.join(parser.parts)).strip()
                if text:
                    chapters.append(text)
            return CHAPTER_MARKER.join(chapters)
    raise ValueError('Choose a PDF, EPUB, or UTF-8 TXT file')
