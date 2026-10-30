import argparse
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import traceback
from .converter import batch, create_job, run_job
from .project_manager import ROOT, initialize, load_config, prepare
from .audio_merger import merge_wavs
from .tts_client import health, ServerUnavailable


def choose(paths, label):
    paths = list(paths)
    if not paths:
        print('Nothing available.')
        return None
    for i, path in enumerate(paths, 1):
        print(f'{i}. {path.parent.name if path.name == "manifest.json" else path.name}')
    answer = input(label + ' (number, Enter to cancel): ').strip()
    if not answer:
        return None
    index = int(answer) - 1
    if not 0 <= index < len(paths):
        raise ValueError('Selection out of range')
    return paths[index]


def edit(path):
    subprocess.run(['notepad.exe', str(path)], check=True)


def review(prepared):
    print('\nPrepared narration:', prepared)
    print(prepared.read_text(encoding='utf-8')[:1800])
    print('\nEPUB chapter separators are marked === CHAPTER BREAK === and are not narrated.')
    while True:
        answer = input('[E]dit in Notepad, [G]enerate, or [C]ancel: ').lower().strip()
        if answer == 'e':
            edit(prepared)
            input('Save your edits and close Notepad, then press Enter: ')
        elif answer in ('g','c'):
            return answer == 'g'


def server(config):
    try:
        print(json.dumps(health(config), indent=2))
        return
    except ServerUnavailable as exc:
        print(exc)
    if input('Launch the existing Chatterbox server? [y/N]: ').lower() != 'y':
        return
    directory = Path(config['server_directory'])
    executable = directory / '.venv/Scripts/python.exe'
    if not executable.exists():
        raise RuntimeError('Existing server Python launcher is missing. Check server_directory in Settings.')
    # Validate before spawning; never repair or reinstall the server environment.
    subprocess.run([str(executable), '-c', 'import sys; print(sys.version)'], check=True)
    log = open(ROOT / 'logs/server-start.log', 'ab')
    try:
        subprocess.Popen([str(executable), 'start.py'], cwd=directory, stdout=log, stderr=log,
                         creationflags=subprocess.CREATE_NO_WINDOW)
    finally:
        log.close()
    print('Launch requested. Check again after initialization; errors are in logs/server-start.log.')


def menu():
    while True:
        print('\n========================================\n              CHAPTERBOX\n       Local Audiobook Factory\n========================================')
        print('1. Convert a document\n2. Batch convert incoming documents\n3. Resume unfinished audiobook\n4. Merge existing audio chunks\n5. Preview/edit prepared text\n6. Check or launch Chatterbox server\n7. Open completed audiobooks\n8. Settings\n9. Exit')
        try:
            option = input('Select an option: ').strip()
            config = load_config()
            if option == '9':
                return
            if option == '1':
                source = input('Paste or drag in a PDF, EPUB, or TXT path: ').strip().strip('"')
                prepared = prepare(source)
                if review(prepared):
                    run_job(create_job(prepared, config))
            elif option == '2':
                sources = sorted(p for p in (ROOT / 'input').rglob('*') if p.suffix.lower() in ('.pdf','.epub','.txt'))
                for p in sources:
                    print(p)
                if input('Generate all listed documents automatically without individual previews? [y/N]: ').lower() == 'y':
                    results = batch(sources, config)
                    for source, output, error in results:
                        print(source, '->', error or output)
            elif option == '3':
                jobs = []
                for path in (ROOT / 'cache').glob('*/manifest.json'):
                    try:
                        data = json.loads(path.read_text(encoding='utf-8'))
                        if data['status'] != 'complete':
                            jobs.append(path)
                    except (ValueError, KeyError):
                        print('Unreadable manifest:', path)
                for path in jobs:
                    print('Job:', path.parent.name)
                path = choose(jobs, 'Resume job using its saved narration and settings')
                if path:
                    run_job(path)
            elif option == '4':
                folder = Path(input('Chunk folder (or cache job folder): ').strip().strip('"'))
                if (folder / 'manifest.json').exists() and (folder / 'chunks').is_dir():
                    run_job(folder / 'manifest.json')
                else:
                    parts = sorted(folder.glob('part_*.wav'))
                    if not parts:
                        raise ValueError('No part_*.wav files found')
                    numbers = [int(p.stem.split('_')[-1]) for p in parts]
                    if numbers != list(range(1,len(parts)+1)):
                        raise ValueError('Chunk numbering has gaps; merge stopped')
                    legacy = folder / 'manifest.json'
                    if legacy.exists() and len(json.loads(legacy.read_text(encoding='utf-8'))['chunks']) != len(parts):
                        raise ValueError('Chunk count differs from manifest')
                    from .project_manager import safe_name
                    output = ROOT / 'output' / safe_name(folder.name) / 'merged.wav'
                    print(merge_wavs(parts, output, config['sample_rate'], config['channels']))
            elif option == '5':
                path = choose(sorted((ROOT / 'prepared').glob('*.txt')), 'Prepared text')
                if path:
                    edit(path)
            elif option == '6':
                server(config)
            elif option == '7':
                os.startfile(ROOT / 'output')
            elif option == '8':
                edit(ROOT / 'config.json')
            else:
                print('Choose 1 through 9.')
        except KeyboardInterrupt:
            print('\nCancelled. Completed chunks are saved.')
        except EOFError:
            return
        except Exception:
            logging.exception('Action failed')
            traceback.print_exc()
            print('Details saved to logs/chapterbox.log')


def main():
    # Legacy Windows consoles may not support every character in a document.
    # This affects display only; prepared text and API payloads remain UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    initialize()
    logging.basicConfig(filename=ROOT/'logs/chapterbox.log', level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s', encoding='utf-8')
    parser = argparse.ArgumentParser(description='ChapterBox audiobook factory')
    parser.add_argument('source', nargs='?', type=Path)
    parser.add_argument('--auto', action='store_true', help='Skip the narration review')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--resume', type=Path)
    args = parser.parse_args()
    if args.resume:
        run_job(args.resume)
    elif args.source:
        prepared = prepare(args.source)
        if args.prepare_only:
            print(prepared)
        elif args.auto or review(prepared):
            run_job(create_job(prepared, load_config()))
    else:
        menu()


if __name__ == '__main__':
    main()
