# Offline Python dependencies

This directory contains the pure-Python `pypdf 6.10.0` wheel used by ScanSplit.
It supports Python 3 on both ARM64 and AMD64. Library code and upstream metadata
are unchanged. The wheel was deterministically repackaged from the installed
upstream distribution using `tools/vendor_pypdf.py`; it is not claimed to be
byte-identical to the wheel hosted by PyPI. Installation-local metadata and
bytecode are excluded. The wheel's own RECORD and the hashes in requirements.txt
and SHA256SUMS are regenerated. The upstream BSD-3-Clause license is included
inside the wheel and as pypdf-LICENSE.txt.

Source: https://github.com/py-pdf/pypdf/tree/6.10.0

Install from the checked-out release without contacting any package index:

```sh
python -m pip install --no-index --find-links vendor --require-hashes -r requirements.txt
```

When upgrading dependencies, include all required wheels and their hashes in the
same commit. The runtime does not fall back to downloads from PyPI.
