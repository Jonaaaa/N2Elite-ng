# Third-Party Notices

N2Elite-ng (this project) is licensed under PolyForm Noncommercial 1.0.0 (see
LICENSE). It incorporates or builds on the following, with thanks:

## amiitool (MIT)
The amiibo cryptography in `n2elite/amiibo/crypto.py` is a Python port of the
algorithm from **amiitool** by Marcos Del Sol Vives (socram8888).

> Copyright (c) 2015-2017 Marcos Del Sol Vives
>
> Permission is hereby granted, free of charge, to any person obtaining a copy
> of this software and associated documentation files (the "Software"), to deal
> in the Software without restriction, including without limitation the rights
> to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
> copies of the Software, and to permit persons to whom the Software is
> furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

## amiibo metadata — AmiiboAPI / amiiboapi.org
The bundled `n2elite/amiibo/amiibo_db.json` (amiibo names/series/type) is public
metadata derived from **amiiboapi.org** (the 8bitDream AmiiboAPI project). Amiibo
figure images are fetched on demand (opt-in) from the same source, and
`n2elite sync` can optionally download the full database and all images from it
for offline use. No Nintendo keys or copyrighted amiibo tag data are included.

## Protocol
The N2 Elite / MFRC522 serial protocol was reverse-engineered from the abandoned
official "N2 Elite Manager" and cross-checked against TagMo
(github.com/HiddenRamblings/TagMo). Only protocol facts (opcodes/behaviour) were
used; no third-party source code was copied.
