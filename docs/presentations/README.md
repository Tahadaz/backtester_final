This folder contains the weekly PPTX generator and the generated presentation.

How to build the PPTX locally

1. Ensure you have Python 3.8+ installed.
2. Install dependency:

```bash
pip install python-pptx
```

3. Run the generator script (it expects your two images in your Downloads folder):

```bash
python scripts/generate_presentation.py
```

4. Output file:

- docs/presentations/weekly_report_2026-04-24.pptx

Notes

- The generator uses placeholder numbers for the example results. To populate with real numbers, either:
  - edit `scripts/generate_presentation.py` to pull a JSON/CSV of results from `C:\Users\taha\Downloads\iLoveZIP_Create`, or
  - replace the placeholder bullet texts manually in PowerPoint after generation.

If you want, I can extract results from `C:\Users\taha\Downloads\iLoveZIP_Create` and update the PPTX automatically.