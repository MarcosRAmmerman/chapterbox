import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class ServerUnavailable(RuntimeError):
    pass


def health(config):
    parts = urlsplit(config['endpoint'])
    url = f'{parts.scheme}://{parts.netloc}/health'
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            result = json.load(response)
        if result.get('model_loaded') is False:
            raise ServerUnavailable('Chatterbox is reachable but its model is not ready')
        return result
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ServerUnavailable(f'Cannot reach Chatterbox at {url}: {exc}') from exc


def generate(text, config):
    allowed = {'speed','exaggeration','cfg_weight','temperature'}
    parameters = config.get('parameters', {})
    if set(parameters) - allowed:
        raise ValueError('Unsupported generation parameters: ' + ', '.join(set(parameters) - allowed))
    payload = {'input': text, 'model': config['model'], 'voice': config['voice'],
               'response_format': 'wav', **parameters}
    request = urllib.request.Request(config['endpoint'], data=json.dumps(payload).encode('utf-8'),
                                     headers={'Content-Type':'application/json','Accept':'audio/wav',
                                              'Authorization':'Bearer local'})
    for attempt in range(config['retries']):
        try:
            with urllib.request.urlopen(request, timeout=config['timeout']) as response:
                data = response.read()
            if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
                raise ValueError('API returned non-WAV data')
            return data
        except urllib.error.HTTPError as exc:
            if exc.code not in (408,429,500,502,503,504) or attempt == config['retries'] - 1:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == config['retries'] - 1:
                raise ServerUnavailable('Speech request failed; cached chunks are preserved')
        if attempt < config['retries'] - 1:
            time.sleep(min(2 ** attempt, 16))
