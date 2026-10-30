import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from contextlib import contextmanager

ROOT = Path(__file__).resolve().parents[1]
DEFAULTS = {'endpoint': 'http://127.0.0.1:4123/v1/audio/speech', 'model': 'chatterbox',
            'voice': 'alloy', 'chunk_chars': 220, 'retries': 3, 'timeout': 600,
            'parameters': {}, 'sample_rate': 24000, 'channels': 1,
            'paragraph_pause': 0.3, 'chapter_pause': 1.0, 'mp3': False,
            'server_directory': r'C:\Users\Marcos\chatterbox-local\chatterbox-tts-api'}


@contextmanager
def job_lock(folder):
    """OS releases this lock even if a conversion process crashes."""
    with open(Path(folder) / '.lock', 'a+b') as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError('This audiobook is already open in another conversion process') from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    return digest(Path(path).read_bytes())


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.partial')
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2).encode('utf-8'))


def safe_name(name):
    value = re.sub(r'[^\w.-]+', '_', name, flags=re.UNICODE).strip(' ._')[:70] or 'book'
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))}:
        value = '_' + value
    return value


def initialize(root=ROOT):
    for name in ('input/pdf','input/epub','input/text','prepared','cache','output','logs'):
        (root / name).mkdir(parents=True, exist_ok=True)


def load_config(root=ROOT):
    config = DEFAULTS.copy()
    path = root / 'config.json'
    if path.exists():
        config.update(json.loads(path.read_text(encoding='utf-8-sig')))
    if not 50 <= config['chunk_chars'] <= 1000 or not 1 <= config['retries'] <= 10:
        raise ValueError('Invalid chunk_chars (50-1000) or retries (1-10) in config.json')
    if config['timeout'] <= 0 or config['sample_rate'] not in (16000,22050,24000,44100,48000) or config['channels'] not in (1,2):
        raise ValueError('Invalid timeout or output audio format')
    if any(not 0 <= config[k] <= 30 for k in ('paragraph_pause','chapter_pause')):
        raise ValueError('Pauses must be between 0 and 30 seconds')
    return config


def prepare(source, root=ROOT):
    from .extractor import extract
    initialize(root)
    source = Path(source).resolve()
    source_digest = file_hash(source)[:12]
    # Re-importing a managed original must not append its hash repeatedly.
    stem = source.stem
    if source.is_relative_to((root / 'input').resolve()) and stem.endswith('-' + source_digest):
        stem = stem[:-13]
    identity = safe_name(stem) + '-' + source_digest
    folder = {'.pdf':'pdf','.epub':'epub','.txt':'text'}.get(source.suffix.lower())
    if folder is None:
        raise ValueError('Only PDF, EPUB, and TXT documents are supported')
    original = root / 'input' / folder / (identity + source.suffix.lower())
    if not original.exists():
        atomic_write(original, source.read_bytes())
    prepared = root / 'prepared' / (identity + '.txt')
    if not prepared.exists():
        text = extract(source)
        if not text.strip():
            raise ValueError('Document contains no narration text')
        atomic_write(prepared, text.encode('utf-8'))
    return prepared
