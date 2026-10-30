"""Smoke test: capture the local fixture and check the SVG is well-formed and layered.

Run with: uv run tests/smoke.py
"""
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parent.parent
out = Path(tempfile.mkdtemp()) / "fixture.svg"
subprocess.run([sys.executable, str(root / "snap.py"), (root / "tests/fixture.html").as_uri(),
                "-o", str(out), "--layers"], check=True)
tree = ET.parse(out)
ns = {"s": "http://www.w3.org/2000/svg"}
ink = "{http://www.inkscape.org/namespaces/inkscape}groupmode"
layers = [g for g in tree.iter("{http://www.w3.org/2000/svg}g") if g.get(ink) == "layer"]
texts = [t.text for t in tree.iter("{http://www.w3.org/2000/svg}text")]
assert len(layers) >= 4, f"expected >=4 layers, got {len(layers)}"
assert "FIXTURE SITE" in texts, "heading should be live text with text-transform applied"
assert any(t.startswith("Body text that wraps") for t in texts), "paragraph lines should be text"
assert list(tree.iter("{http://www.w3.org/2000/svg}image")), "image layer missing"
print(f"ok: {len(layers)} layers, {len(texts)} text lines")
