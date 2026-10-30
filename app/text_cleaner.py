import re
from collections import Counter


def clean_pdf_pages(pages):
    """Remove repeated margins and isolated page numbers, retaining punctuation."""
    lines = [[line.strip() for line in page.splitlines()] for page in pages]
    edges = Counter()
    for page in lines:
        nonempty = [line for line in page if line]
        edges.update(set(nonempty[:1] + nonempty[-1:]))
    repeated = {line for line, count in edges.items() if len(pages) >= 3 and count >= max(3, len(pages) * .6)}
    result = []
    for page in lines:
        nonempty = [i for i, line in enumerate(page) if line]
        margins = set(nonempty[:1] + nonempty[-1:])
        kept = [line for i, line in enumerate(page)
                if not (i in margins and (line in repeated or re.fullmatch(r'(?:Page\s+)?\d+', line, re.I)))]
        text = '\n'.join(kept)
        # Only explicit discretionary hyphens are removed. Ordinary hyphens remain.
        text = re.sub(r'\u00ad\n(?=[a-záéíóúñü])', '', text)
        text = re.sub(r'(?<=\w)-\n(?=[a-záéíóúñü])', '-', text)
        paragraphs = [re.sub(r'\s*\n\s*', ' ', block).strip()
                      for block in re.split(r'\n\s*\n', text)]
        result.append('\n\n'.join(p for p in paragraphs if p))
    return '\n\n'.join(result).strip()


def split_text(text, limit=220):
    if not 50 <= limit <= 1000:
        raise ValueError('Chunk length must be 50 through 1000 characters')
    result = []
    for paragraph in re.split(r'\n\s*\n', text.strip()):
        paragraph = re.sub(r'\s+', ' ', paragraph).strip()
        if not paragraph:
            continue
        sentences = re.split(r'(?<=[.!?])\s+|(?<=[.!?][”"’])\s+', paragraph)
        current = ''
        for sentence in sentences:
            while len(sentence) > limit:
                if current:
                    result.append({'text': current, 'paragraph_end': False})
                    current = ''
                cut = sentence.rfind(' ', 0, limit + 1)
                cut = cut if cut > 0 else limit
                result.append({'text': sentence[:cut], 'paragraph_end': False})
                sentence = sentence[cut:].lstrip()
            if current and len(current) + len(sentence) + 1 > limit:
                result.append({'text': current, 'paragraph_end': False})
                current = ''
            current = (current + ' ' + sentence).strip()
        if current:
            result.append({'text': current, 'paragraph_end': True})
        elif result:
            result[-1]['paragraph_end'] = True
    return result
