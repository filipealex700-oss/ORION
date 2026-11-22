import os
import sys

from ctranslate2.converters import TransformersConverter

BASE = os.path.dirname(os.path.abspath(__file__))
src = os.path.join(BASE, "ct2_build", "fused")
dst = os.path.join(BASE, "ct2_build", "ct2")

converter = TransformersConverter(src)
converter.convert(dst, quantization="float16")
print("CT2 guardado em", dst)
