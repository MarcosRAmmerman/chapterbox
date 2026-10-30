r"""Run from the project root: .venv\Scripts\python.exe tests/run_tests.py"""
import logging
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
(ROOT/'logs').mkdir(exist_ok=True)
logging.basicConfig(filename=ROOT/'logs/test-errors.log', level=logging.INFO)
suite = unittest.defaultTestLoader.discover(str(ROOT/'tests'))
with open(ROOT/'logs/automated-tests.txt','w',encoding='utf-8') as stream:
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
print((ROOT/'logs/automated-tests.txt').read_text(encoding='utf-8'))
raise SystemExit(not result.wasSuccessful())
