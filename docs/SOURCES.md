# Sources & References

n2elite-ng was built by reverse-engineering the N2 Elite / Amiiqo USB device and
porting concepts from open sources. Big thanks to everyone whose work made this
possible. (Licenses/attributions for bundled/ported code are in
`THIRD_PARTY_NOTICES.md`.)

## N2 Elite / amiibo protocol
- **TagMo** — the inspiration and the cross-check for the N2 command set:
  <https://github.com/HiddenRamblings/TagMo>
- **YobiWiki — N2 Elite** — N2 proprietary command reference:
  <https://wiki.yobi.be/index.php/N2_Elite>
- **Amiibo Reverse Engineering (Kevin Brewster)** — NTAG215 + amiibo crypto notes:
  <https://kevinbrewster.github.io/Amiibo-Reverse-Engineering/>
- **miguelbalboa/rfid** — the MFRC522 library the desktop app was ported from
  (register map, PCD_Init, transceive): <https://github.com/miguelbalboa/rfid>
- NXP MFRC522 datasheet (UART register interface).
- **How to use N2 Elite with a USB NFC reader (guide)** — confirmed the CP210x +
  MFRC522 hardware:
  <https://3dslatestinformation.wordpress.com/2017/04/22/how-to-use-n2-elite-with-usb-nfc-reader-on-your-pcmac/>

## Amiibo crypto & metadata
- **amiitool (socram8888)** — the amiibo AES-128-CTR + HMAC-SHA256 algorithm we
  ported: <https://github.com/socram8888/amiitool>
- **libamiibo (Falco20019)** — amiibo dump parsing reference:
  <https://github.com/Falco20019/libamiibo>
- **AmiiboAPI — amiiboapi.org** — amiibo names/series/type + figure images
  (bundled `amiibo_db.json`, opt-in images): <https://www.amiiboapi.org/>
  - 8bitDream fork (image host): <https://github.com/8bitDream/AmiiboAPI>
  - N3evin original: <https://github.com/N3evin/AmiiboAPI>
- **AmiiboDB**: <https://github.com/AmiiboDB/Amiibo>

## Original (abandoned) N2 Elite software & docs — recovered via the Wayback Machine
The original vendors are gone; these were used only to reverse-engineer the serial
protocol (static analysis) and to read the manual:
- N2 Elite Manager v2.2.0 (.NET) and v1.1 (Qt) — from `n2elite.ca` / `n2elite.com`
  downloads on <https://web.archive.org/>
- N2 Elite user manual (`N2-Elite-Manual-v1.pdf`) — same archive.
- Silicon Labs CP210x USB-to-UART VCP drivers: <https://www.silabs.com/>

## Build tooling
- **PyInstaller** — single-file binaries: <https://pyinstaller.org/>
- **python-build-standalone (astral-sh)** — portable Windows Python used to
  cross-build the `.exe` under 64-bit Wine, no host changes:
  <https://github.com/astral-sh/python-build-standalone>
- **Wine** — <https://www.winehq.org/>

## Hardware
N2 Elite / Amiiqo USB reader-writer: NXP **MFRC522** NFC frontend behind a Silicon
Labs **CP2102** USB-UART bridge (VID:PID `10c4:ea60`).
