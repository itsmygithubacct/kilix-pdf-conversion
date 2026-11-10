"""Page OCR with a per-page choice between Tesseract and RapidOCR.

Submodules import numpy and Pillow; import them only where OCR is used so the
base package still loads without the OCR runtime.
"""
