"""Type Sinhala text and see its FM version. Run:  .venv\\Scripts\\python try_fm.py"""

from sinhalasubs.fm_converter import fm_runs

while True:
    text = input("Sinhala text (Enter to quit): ")
    if not text:
        break
    for chunk, english in fm_runs(text):
        print(f"  {'EN' if english else 'FM'}  {chunk!r}")
