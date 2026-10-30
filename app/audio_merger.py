"""Strict RIFF decoding and atomic PCM16 assembly, without an AI/audio dependency."""
import array
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import wave


def read_wav(path):
    data = Path(path).read_bytes()
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError(f'{path}: not a RIFF WAV')
    end = struct.unpack_from('<I', data, 4)[0] + 8
    if end > len(data):
        raise ValueError(f'{path}: truncated RIFF')
    fmt = payload = None
    pos = 12
    while pos + 8 <= end:
        tag, size = struct.unpack_from('<4sI', data, pos)
        pos += 8
        if pos + size > end:
            raise ValueError(f'{path}: truncated {tag!r} chunk')
        if tag == b'fmt ':
            fmt = data[pos:pos + size]
        elif tag == b'data':
            payload = data[pos:pos + size]
        pos += size + size % 2
    if fmt is None or len(fmt) < 16 or not payload:
        raise ValueError(f'{path}: missing format or empty audio')
    kind, channels, rate, byte_rate, align, bits = struct.unpack_from('<HHIIHH', fmt)
    if kind == 65534 and len(fmt) >= 40:
        kind = struct.unpack_from('<I', fmt, 24)[0]
        if fmt[28:40] != bytes.fromhex('00001000800000aa00389b71'):
            raise ValueError('Unsupported extensible WAV subformat')
    if kind not in (1, 3) or bits not in ((8, 16, 24, 32) if kind == 1 else (32, 64)):
        raise ValueError(f'Unsupported WAV encoding: {kind}, {bits} bits')
    if not 1 <= channels <= 32 or not 1000 <= rate <= 384000:
        raise ValueError('Invalid channel count or sample rate')
    width = bits // 8
    if align != channels * width or byte_rate != rate * align or len(payload) % align:
        raise ValueError('Invalid WAV block alignment or truncated frames')
    samples = array.array('f')
    if kind == 3:
        for (value,) in struct.iter_unpack('<f' if bits == 32 else '<d', payload):
            if not math.isfinite(value):
                raise ValueError('WAV contains non-finite samples')
            samples.append(max(-1.0, min(1.0, value)))
    elif bits == 8:
        samples.extend((v - 128) / 128 for v in payload)
    else:
        scale = float(1 << (bits - 1))
        samples.extend(int.from_bytes(payload[i:i + width], 'little', signed=True) / scale
                       for i in range(0, len(payload), width))
    return {'format': 'FLOAT' if kind == 3 else 'PCM', 'bits': bits,
            'channels': channels, 'rate': rate, 'frames': len(samples) // channels}, samples


def inspect_wav(path):
    return read_wav(path)[0]


def valid_wav(path):
    try:
        inspect_wav(path)
        return True
    except (OSError, ValueError, struct.error):
        return False


def normalize(info, samples, rate, channels):
    """Linear resampling; downmix all channels to mono, optionally duplicate stereo."""
    source_channels = info['channels']
    if channels not in (1, 2):
        raise ValueError('Output must be mono or stereo')
    frames = info['frames']
    count = max(1, round(frames * rate / info['rate']))
    out = bytearray(count * channels * 2)
    def value(frame, channel):
        if source_channels == channels:
            return samples[frame * source_channels + channel]
        return sum(samples[frame * source_channels:(frame + 1) * source_channels]) / source_channels
    for i in range(count):
        position = min(i * info['rate'] / rate, frames - 1)
        left = int(position)
        fraction = position - left
        for channel in range(channels):
            a = value(left, channel)
            b = value(min(left + 1, frames - 1), channel)
            v = max(-32768, min(32767, round((a + (b - a) * fraction) * 32768)))
            struct.pack_into('<h', out, (i * channels + channel) * 2, v)
    return out


def merge_wavs(paths, output, rate=24000, channels=1, pauses=None):
    paths = list(map(Path, paths))
    output = Path(output)
    if not paths:
        raise ValueError('No audio chunks selected')
    if rate < 1000 or channels not in (1, 2):
        raise ValueError('Invalid output format')
    if output.resolve() in [p.resolve() for p in paths]:
        raise ValueError('Output cannot overwrite a source chunk')
    pauses = list(pauses) if pauses is not None else [0] * len(paths)
    if len(pauses) != len(paths) or any(p < 0 for p in pauses):
        raise ValueError('Invalid pause list')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(suffix='.wav', dir=output.parent)
    os.close(fd)
    try:
        with wave.open(temporary, 'wb') as writer:
            writer.setparams((channels, 2, rate, 0, 'NONE', 'not compressed'))
            for index, path in enumerate(paths):
                info, samples = read_wav(path)
                writer.writeframes(normalize(info, samples, rate, channels))
                if index < len(paths) - 1:
                    writer.writeframes(b'\0' * (round(pauses[index] * rate) * channels * 2))
        with wave.open(temporary, 'rb') as check:
            if check.getnframes() == 0:
                raise ValueError('Merged output is empty')
        os.replace(temporary, output)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return output


def export_mp3(wav, output):
    encoder = shutil.which('ffmpeg')
    if not encoder:
        raise RuntimeError('MP3 requires FFmpeg on PATH. Your WAV is already saved.')
    output = Path(output)
    temporary = output.with_suffix('.partial.mp3')
    try:
        subprocess.run([encoder, '-nostdin', '-y', '-i', str(wav), '-codec:a',
                        'libmp3lame', '-q:a', '2', str(temporary)], check=True,
                       capture_output=True, creationflags=0x08000000 if os.name == 'nt' else 0)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
