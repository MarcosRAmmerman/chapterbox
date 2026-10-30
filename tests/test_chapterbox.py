import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
import urllib.error
import wave
import zipfile

from app.audio_merger import inspect_wav, valid_wav, merge_wavs
from app.converter import create_job, run_job, batch, plan
from app.extractor import extract, CHAPTER_MARKER
from app.project_manager import DEFAULTS, initialize, prepare, safe_name
from app.text_cleaner import clean_pdf_pages, split_text
from app import tts_client


def wav_data(kind=1, bits=16, rate=24000, channels=1, frames=24):
    sample = struct.pack('<f', .25) if kind == 3 else (b'\xa0' if bits == 8 else int(2**(bits-3)).to_bytes(bits//8,'little',signed=True))
    payload = sample * frames * channels
    fmt = struct.pack('<HHIIHH',kind,channels,rate,rate*channels*(bits//8),channels*(bits//8),bits)
    body = b'WAVEfmt ' + struct.pack('<I',16) + fmt + b'data' + struct.pack('<I',len(payload)) + payload
    return b'RIFF' + struct.pack('<I',len(body)) + body


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        initialize(self.root)
        self.config = dict(DEFAULTS, parameters={})

    def tearDown(self):
        self.temp.cleanup()

    def file(self,name,data):
        path = self.root / name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
        return path

    def test_pdf_cleanup(self):
        pages = [f'Book heading\nHola, señor.\nDialogue stays!\n\nAnother para.\n{i}' for i in range(1,4)]
        cleaned = clean_pdf_pages(pages)
        self.assertNotIn('Book heading',cleaned)
        self.assertNotIn('\n1',cleaned)
        self.assertIn('Hola, señor. Dialogue stays!\n\nAnother para.',cleaned)
        self.assertEqual(clean_pdf_pages(['soft\u00ad\nware and well-\nknown']), 'software and well-known')

    def test_splitting(self):
        text = '“Hola, señor.” Está aquí. ' + 'word '*30 + '\n\nSecond paragraph!'
        pieces = split_text(text,50)
        self.assertTrue(all(len(c['text'])<=50 for c in pieces))
        self.assertEqual(' '.join(c['text'] for c in pieces).split(),text.split())
        self.assertTrue(pieces[-1]['paragraph_end'])
        self.assertGreaterEqual(sum(c['paragraph_end'] for c in pieces),2)

    def test_formats_and_normalization(self):
        paths = []
        for kind,bits,rate,ch in [(1,8,12000,1),(1,16,24000,2),(1,24,48000,1),(1,32,24000,1),(3,32,24000,1)]:
            p = self.file(f'{kind}-{bits}.wav',wav_data(kind,bits,rate,ch))
            self.assertTrue(valid_wav(p))
            self.assertEqual(inspect_wav(p)['bits'],bits)
            paths.append(p)
        output = merge_wavs(paths,self.root/'merged.wav')
        with wave.open(str(output)) as reader:
            self.assertEqual(reader.getparams()[:3],(1,2,24000))
            self.assertEqual(reader.getnframes(),48+24+12+24+24)

    def test_invalid_audio_and_atomic_merge(self):
        p = self.file('bad.wav',wav_data()[:-3])
        self.assertFalse(valid_wav(p))
        output = self.file('output.wav',b'existing output')
        with self.assertRaises(ValueError):
            merge_wavs([p],output)
        self.assertEqual(output.read_bytes(),b'existing output')
        with self.assertRaises(ValueError):
            merge_wavs([],output)

    def test_cache_invalidation(self):
        p = self.file('book.txt',b'A short story.')
        first = create_job(p,self.config,self.root)
        self.assertEqual(first,create_job(p,self.config,self.root))
        self.assertNotEqual(first,create_job(p,dict(self.config,voice='other'),self.root))
        p.write_text('Changed narration.',encoding='utf-8')
        self.assertNotEqual(first,create_job(p,self.config,self.root))
        self.assertTrue(first.exists())

    def test_resume_and_corrupt_chunk(self):
        p = self.file('book.txt',b'First paragraph.\n\nSecond paragraph.')
        job = create_job(p,self.config,self.root)
        calls = []
        def fail_second(text, config):
            calls.append(text)
            if len(calls)==2:
                raise RuntimeError('simulated failure')
            return wav_data()
        with self.assertRaises(RuntimeError):
            run_job(job,self.root,client=fail_second,check=lambda c:None,progress=lambda s:None)
        resumed = []
        run_job(job,self.root,client=lambda t,c:(resumed.append(t) or wav_data()),check=lambda c:None,progress=lambda s:None)
        self.assertEqual(resumed,['Second paragraph.'])
        (job.parent/'chunks/part_0001.wav').write_bytes(b'corrupt')
        resumed.clear()
        run_job(job,self.root,client=lambda t,c:(resumed.append(t) or wav_data()),check=lambda c:None,progress=lambda s:None)
        self.assertEqual(resumed,['First paragraph.'])
        self.assertEqual(json.loads(job.read_text())['status'],'complete')

    def test_cancel_preserves_progress(self):
        p = self.file('book.txt',b'One.\n\nTwo.')
        job = create_job(p,self.config,self.root)
        responses = iter([wav_data(),KeyboardInterrupt()])
        def client(t,c):
            value = next(responses)
            if isinstance(value,BaseException): raise value
            return value
        with self.assertRaises(KeyboardInterrupt):
            run_job(job,self.root,client=client,check=lambda c:None,progress=lambda s:None)
        self.assertTrue(valid_wav(job.parent/'chunks/part_0001.wav'))
        self.assertEqual(json.loads(job.read_text())['status'],'cancelled')

    def test_filename_collisions_and_originals(self):
        a = self.file('one/same.txt',b'First')
        b = self.file('two/same.txt',b'Second')
        self.assertNotEqual(prepare(a,self.root),prepare(b,self.root))
        self.assertEqual(a.read_bytes(),b'First')
        self.assertEqual(safe_name('CON'),'_CON')
        self.assertNotIn(':',safe_name('bad:name?'))
        managed = next((self.root/'input/text').glob('same-*.txt'))
        before = set((self.root/'input/text').glob('*'))
        prepare(managed,self.root)
        self.assertEqual(before,set((self.root/'input/text').glob('*')))

    def test_changed_manifest_request_never_reuses_audio(self):
        p=self.file('book.txt',b'Hi.')
        job=create_job(p,self.config,self.root)
        run_job(job,self.root,client=lambda t,c:wav_data(),check=lambda c:None,progress=lambda s:None)
        saved=json.loads(job.read_text())
        saved['config']['voice']='different'
        job.write_text(json.dumps(saved))
        calls=[]
        run_job(job,self.root,client=lambda t,c:(calls.append(t) or wav_data()),check=lambda c:None,progress=lambda s:None)
        self.assertEqual(calls,['Hi.'])

    def test_chapter_files_and_pauses(self):
        p=self.file('chapters.txt',('First.'+CHAPTER_MARKER+'Second.').encode())
        job=create_job(p,self.config,self.root)
        output=run_job(job,self.root,client=lambda t,c:wav_data(),check=lambda c:None,progress=lambda s:None)
        self.assertEqual(len(list(output.parent.glob('chapter_*.wav'))),2)
        self.assertEqual(inspect_wav(output)['frames'],48+24000)

    def test_float64_extensible_and_nonfinite(self):
        payload=struct.pack('<dd',.5,-.5)
        fmt=struct.pack('<HHIIHH',3,1,24000,192000,8,64)
        body=b'WAVEfmt '+struct.pack('<I',16)+fmt+b'data'+struct.pack('<I',len(payload))+payload
        path=self.file('double.wav',b'RIFF'+struct.pack('<I',len(body))+body)
        self.assertTrue(valid_wav(path))
        fmt=struct.pack('<HHIIHHHHI',65534,1,24000,48000,2,16,22,16,0)+bytes.fromhex('0100000000001000800000aa00389b71')
        body=b'WAVEfmt '+struct.pack('<I',40)+fmt+b'data'+struct.pack('<I',2)+b'\0\0'
        path=self.file('extensible.wav',b'RIFF'+struct.pack('<I',len(body))+body)
        self.assertTrue(valid_wav(path))
        data=bytearray(wav_data(3,32))
        data[44:48]=struct.pack('<f',float('nan'))
        self.assertFalse(valid_wav(self.file('nan.wav',data)))

    def test_batch_continues(self):
        def convert(source):
            if source=='bad': raise ValueError('bad document')
            return source
        result = batch(['bad','good'],self.config,self.root,convert)
        self.assertEqual(len(result),2)
        self.assertEqual(result[1][1],'good')

    def test_batch_stops_for_server(self):
        def convert(source): raise tts_client.ServerUnavailable('offline')
        self.assertEqual(len(batch(['a','b'],self.config,self.root,convert)),1)

    def test_http_retry_and_permanent_error(self):
        transient = urllib.error.HTTPError('local',503,'unavailable',{},None)
        with patch('urllib.request.urlopen',side_effect=[transient,io.BytesIO(wav_data())]) as call, patch('time.sleep'):
            self.assertTrue(tts_client.generate('Hi',self.config).startswith(b'RIFF'))
            self.assertEqual(call.call_count,2)
        with patch('urllib.request.urlopen',side_effect=urllib.error.HTTPError('local',400,'bad',{},None)) as call:
            with self.assertRaises(urllib.error.HTTPError): tts_client.generate('Hi',self.config)
            self.assertEqual(call.call_count,1)

    def test_request_failure(self):
        with patch('urllib.request.urlopen',side_effect=urllib.error.URLError('offline')),patch('time.sleep'):
            with self.assertRaises(tts_client.ServerUnavailable): tts_client.generate('Hi',self.config)
        with patch('urllib.request.urlopen',return_value=io.BytesIO(b'not audio')):
            with self.assertRaises(ValueError): tts_client.generate('Hi',self.config)

    def test_epub_spine_order(self):
        p = self.root/'book.epub'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('META-INF/container.xml','<container><rootfile full-path="OPS/book.opf"/></container>')
            z.writestr('OPS/book.opf','<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="a.xhtml" media-type="application/xhtml+xml"/><item id="b" href="b.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
            z.writestr('OPS/a.xhtml','<p>Last, señor.</p>')
            z.writestr('OPS/b.xhtml','<p>First.</p><p>Dialogue.</p>')
        text = extract(p)
        self.assertLess(text.index('First'),text.index('Last'))
        self.assertIn(CHAPTER_MARKER,text)
        chunks = plan(text,self.config)
        self.assertEqual({c['chapter'] for c in chunks},{1,2})
        self.assertNotIn('CHAPTER BREAK',' '.join(c['text'] for c in chunks))

    def test_real_pdf_extraction_and_scanned_detection(self):
        try:
            from pypdf import PdfWriter
            from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        except ImportError:
            self.skipTest('pypdf not installed')
        writer=PdfWriter()
        page=writer.add_blank_page(width=300,height=300)
        blank=self.root/'blank.pdf'
        writer.write(blank)
        with self.assertRaisesRegex(ValueError,'no extractable text'): extract(blank)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 10 200 Td (A test paragraph.) Tj 0 -60 Td (Another paragraph.) Tj ET')
        page[NameObject('/Contents')]=writer._add_object(stream)
        path=self.root/'text.pdf'
        writer.write(path)
        self.assertIn('A test paragraph.',extract(path))
        self.assertIn('A test paragraph.\n\nAnother paragraph.',extract(path))


if __name__ == '__main__':
    unittest.main()
