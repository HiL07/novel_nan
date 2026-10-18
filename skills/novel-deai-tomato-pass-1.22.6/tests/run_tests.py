# -*- coding: utf-8 -*-
"""一键跑全部测试。

用法: python tests/run_tests.py（Windows: run_tests.bat；macOS/Linux: ./run_tests.sh）
退出码: 0=全过, 1=有失败。
"""
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS))

loader = unittest.TestLoader()
suite = loader.discover(str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS))
runner = unittest.TextTestRunner(verbosity=2)
result = runner.run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
