import json
import logging
from pathlib import Path
import shutil
from . import tts_client
from .audio_merger import valid_wav, merge_wavs, export_mp3
from .extractor import CHAPTER_MARKER
from .project_manager import ROOT, atomic_write, digest, file_hash, save_json, safe_name
from .text_cleaner import split_text


def display(message):
    print(message, flush=True)


def request_signature(text, config):
    return digest(json.dumps({'text':text, **{key:config[key] for key in
                  ('endpoint','model','voice','parameters')}},sort_keys=True).encode('utf-8'))


def plan(text, config):
    chunks = []
    chapters = text.split(CHAPTER_MARKER.strip())
    for chapter, body in enumerate(chapters, 1):
        pieces = split_text(body, config['chunk_chars'])
        for piece in pieces:
            piece.update(chapter=chapter, pause=config['paragraph_pause'] if piece['paragraph_end'] else 0)
        if pieces and chapter < len(chapters):
            pieces[-1]['pause'] = config['chapter_pause']
        chunks.extend(pieces)
    return chunks


def create_job(prepared, config, root=ROOT):
    prepared = Path(prepared)
    text = prepared.read_text(encoding='utf-8-sig')
    chunks = plan(text, config)
    if not chunks:
        raise ValueError('Prepared text is empty')
    relevant = {k:config[k] for k in ('endpoint','model','voice','parameters','chunk_chars',
                                     'sample_rate','channels','paragraph_pause','chapter_pause','mp3')}
    fingerprint = digest(json.dumps({'version':1,'text':text,'config':relevant}, sort_keys=True).encode())
    job = root / 'cache' / (safe_name(prepared.stem)[:55] + '-' + fingerprint[:16])
    manifest_path = job / 'manifest.json'
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding='utf-8'))
        if old.get('fingerprint') != fingerprint:
            raise ValueError('Cache fingerprint collision or damaged manifest')
        return manifest_path
    (job / 'chunks').mkdir(parents=True, exist_ok=True)
    manifest = {'version':1,'name':job.name,'prepared':str(prepared.resolve()),
                'source_hash':digest(text.encode()),'fingerprint':fingerprint,'config':config,
                'status':'pending','chunks':chunks}
    atomic_write(job / 'narration.txt', text.encode('utf-8'))
    save_json(manifest_path, manifest)
    return manifest_path


def run_job(manifest_path, root=ROOT, client=tts_client.generate, progress=display, check=tts_client.health):
    from .project_manager import job_lock
    with job_lock(Path(manifest_path).parent):
        return _run_job(manifest_path, root, client, progress, check)


def _run_job(manifest_path, root, client, progress, check):
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    config = manifest['config']
    folder = manifest_path.parent
    paths = [folder / 'chunks' / f'part_{i:04d}.wav' for i in range(1,len(manifest['chunks'])+1)]
    checked = False
    try:
        manifest['status'] = 'generating'
        for i, (chunk, path) in enumerate(zip(manifest['chunks'], paths), 1):
            signature = request_signature(chunk['text'], config)
            reusable = (chunk.get('request_signature') == signature and path.exists()
                        and chunk.get('sha256') == file_hash(path) and valid_wav(path))
            if not reusable:
                if not checked:
                    check(config)
                    checked = True
                progress(f'[{i}/{len(paths)}] generating; completed: {i-1}; failed: 0')
                data = client(chunk['text'], config)
                staging = path.with_suffix('.incoming.wav')
                try:
                    atomic_write(staging, data)
                    if not valid_wav(staging):
                        raise ValueError(f'Chunk {i}: corrupt WAV response')
                    if path.exists():
                        backup = path.with_name(path.name + '.' + file_hash(path)[:12] + '.invalid')
                        if not backup.exists():
                            shutil.copy2(path, backup)
                    staging.replace(path)
                finally:
                    staging.unlink(missing_ok=True)
                chunk['sha256'] = file_hash(path)
                chunk['request_signature'] = signature
            else:
                progress(f'[{i}/{len(paths)}] cached')
            chunk['status'] = 'complete'
            manifest['completed'] = i
            manifest.pop('error', None)
            save_json(manifest_path, manifest)
        manifest['status'] = 'merging'
        save_json(manifest_path, manifest)
        output_dir = root / 'output' / safe_name(manifest['name'])
        output = output_dir / (safe_name(manifest['name']) + '.wav')
        merge_wavs(paths, output, config['sample_rate'], config['channels'], [c['pause'] for c in manifest['chunks']])
        chapter_ids = sorted({c['chapter'] for c in manifest['chunks']})
        if len(chapter_ids) > 1:
            for chapter in chapter_ids:
                selected = [(p,c) for p,c in zip(paths,manifest['chunks']) if c['chapter'] == chapter]
                merge_wavs([p for p,c in selected], output_dir / f'chapter_{chapter:03d}.wav',
                           config['sample_rate'], config['channels'], [c['pause'] for p,c in selected])
        manifest['output'] = str(output.resolve())
        if config['mp3']:
            export_mp3(output, output.with_suffix('.mp3'))
        manifest['status'] = 'complete'
        manifest['failed'] = 0
        save_json(manifest_path, manifest)
        progress(f'DONE: {output}')
        return output
    except BaseException as exc:
        manifest['status'] = 'cancelled' if isinstance(exc, KeyboardInterrupt) else 'failed'
        manifest['error'] = str(exc) or type(exc).__name__
        manifest['failed'] = 1
        save_json(manifest_path, manifest)
        logging.exception('Conversion failed: %s', manifest_path)
        progress(f'Failed: {manifest["error"]}. Saved progress: {manifest.get("completed",0)}/{len(paths)}.')
        raise


def batch(sources, config, root=ROOT, convert=None):
    from .project_manager import prepare
    convert = convert or (lambda source: run_job(create_job(prepare(source, root), config, root), root))
    results = []
    for source in sources:
        try:
            results.append((str(source), str(convert(source)), None))
        except tts_client.ServerUnavailable as exc:
            logging.exception('Batch stopped because server is unavailable')
            results.append((str(source), None, str(exc)))
            break
        except Exception as exc:
            logging.exception('Batch document failed: %s', source)
            results.append((str(source), None, str(exc)))
    return results


def import_legacy(source_cache, prepared, config, root=ROOT):
    """Copy verified historical chunks; retain exact historical chunk boundaries."""
    source_cache = Path(source_cache)
    legacy = json.loads((source_cache / 'manifest.json').read_text(encoding='utf-8'))
    config = dict(config, **{k:legacy[k] for k in ('endpoint','voice','model')})
    config.update(paragraph_pause=0, chapter_pause=0, mp3=False)
    fingerprint = digest(json.dumps(legacy, sort_keys=True).encode())
    target = root / 'cache' / ('The_Mimis_legacy-' + fingerprint[:12])
    manifest_path = target / 'manifest.json'
    if manifest_path.exists():
        return manifest_path
    (target / 'chunks').mkdir(parents=True, exist_ok=True)
    chunks = []
    for i, text in enumerate(legacy['chunks'],1):
        path = source_cache / f'part_{i:04d}.wav'
        if not valid_wav(path):
            raise ValueError(f'Legacy chunk {i} is invalid; migration stopped')
        destination = target / 'chunks' / path.name
        atomic_write(destination, path.read_bytes())
        chunks.append({'text':text,'chapter':1,'pause':0,'paragraph_end':False,
                       'sha256':file_hash(destination),'status':'complete',
                       'request_signature':request_signature(text,config)})
    save_json(manifest_path, {'version':1,'name':'The_Mimis','prepared':str(prepared),
                             'fingerprint':fingerprint,'source_hash':digest(legacy['source_text'].encode()),
                             'config':config,'status':'complete','completed':len(chunks),
                             'chunks':chunks,'legacy_origin':str(source_cache.resolve()),
                             'output':str((root/'output/The_Mimis/The_Mimis.wav').resolve())})
    atomic_write(target / 'narration.txt', legacy['source_text'].encode('utf-8'))
    return manifest_path
