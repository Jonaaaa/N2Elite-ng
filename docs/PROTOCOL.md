# N2 Elite / Amiiqo Protocol Reference (CONFIRMED from official app decompile)

Source of truth: decompiled `N2EliteManager.exe` v2.2.0 (class `N2EliteManager.TagReader`),
which is a C# port of the `miguelbalboa/rfid` MFRC522 library over a serial bridge.

The dongle = **NXP MFRC522** exposed over a **CP2102 UART**. The PC implements the
entire MFRC522 + ISO14443-3A + NTAG215 + N2 stack and drives the chip by reading/
writing MFRC522 **registers** over the serial line.

## 1. Serial register bridge (genuine MFRC522 UART interface) — CONFIRMED
Byte-level, strictly request/response, no extra framing or checksum at this layer:
- **Write register:** TX `reg & 0x3F` (bit7=0) → RX 1 byte (address echo, discard)
  → TX `value`  (the value byte is NOT echoed).
- **Read register:**  TX `(reg & 0x3F) | 0x80` (bit7=1) → RX 1 byte = register value.
- **Read FIFO n bytes:** repeat "read register FIFODataReg(0x09)" n times.

### Connect / baud handshake (`PCD_Reset`) — CONFIRMED
1. Open host port @ **9600 baud** (device default after power-on / soft reset).
2. Write CommandReg(0x01) = 0x0F (PCD_SoftReset); sleep 50 ms; keep host @ 9600.
3. Poll CommandReg(0x01) until bit 0x10 (PowerDown) clears.
4. Write SerialSpeedReg(0x1F) = **0x1C**; sleep 10 ms.
5. Switch host port to **921600 baud** (0xE1000).
6. Confirm by reading SerialSpeedReg(0x1F) == 0x1C (retry up to 128×).
Recovery: if a prior session left the chip @ 921600, soft-reset @ 921600 first,
then reopen @ 9600.

### PCD_Init register writes — CONFIRMED
| Reg (hex) | Name          | Value |
|-----------|---------------|-------|
| 0x2A | TModeReg          | 0x8D |
| 0x2B | TPrescalerReg     | 0xA9 |
| 0x2C | TReloadRegH       | 0x03 |
| 0x2D | TReloadRegL       | 0xE8 |
| 0x15 | TxASKReg          | 0x40 |
| 0x11 | ModeReg           | 0x3D |
| 0x26 | RFCfgReg (RxGain) | 0x40 |
then AntennaOn: TxControlReg(0x14) |= 0x03.

### MFRC522 registers used (subset)
CommandReg 0x01, ComIrqReg 0x04, DivIrqReg 0x05, ErrorReg 0x06, Status2Reg 0x08,
FIFODataReg 0x09, FIFOLevelReg 0x0A, ControlReg 0x0C, BitFramingReg 0x0D, CollReg 0x0E,
ModeReg 0x11, TxControlReg 0x14, TxASKReg 0x15, RFCfgReg 0x26, SerialSpeedReg 0x1F,
CRCResultRegH 0x21, CRCResultRegL 0x22, TModeReg 0x2A, VersionReg 0x37.

### PCD commands
Idle 0x00, CalcCRC 0x03, Transceive 0x0C, SoftReset 0x0F.

### Transceive (`PCD_CommunicateWithPICC`) — standard MFRC522
Idle → clear ComIrq (0x7F) → flush FIFO (FIFOLevelReg |= 0x80) → write FIFO →
BitFramingReg = rxAlign<<4 | txLastBits → CommandReg = Transceive →
BitFramingReg |= 0x80 (StartSend) → poll ComIrqReg for **waitIRq = 0x30** (RxIRq|IdleIRq),
timeout on bit 0x01 (TimerIRq) → check ErrorReg & 0x13 → read FIFOLevelReg = n →
read n FIFO bytes → validBits = ControlReg & 0x07. CRC_A appended in **software**
(`CrcA.ComputeCrc`, ISO14443-A, poly 0x8408, init 0x6363) and the 2 CRC bytes are
stripped from the reply by `NfcA.transceive`.

## 2. Tag activation (ISO14443-3A) — standard
REQA (0x26) / WUPA (0x52) → ATQA; anticollision + SELECT cascades (NTAG215 = 7-byte
UID, 2 cascade levels with CT 0x88, SEL 0x93/0x95) → UID + SAK; tag now ACTIVE.
PICC commands: REQA 0x26, WUPA 0x52, CT 0x88, SEL_CL1 0x93, SEL_CL2 0x95, HLTA 0x50,
MF_READ 0x30, UL_WRITE 0xA2.

## 3. N2 Elite / NTAG215 command set (sent via transceive, CRC auto)
| Op   | Name           | Syntax                          | Returns / notes            |
|------|----------------|---------------------------------|----------------------------|
| 0x30 | READ           | `30 [page]`                     | 16 bytes                   |
| 0x3A | FAST_READ      | `3a [start] [end]`              | (end-start+1)*4 bytes      |
| 0xA2 | WRITE (UL)     | `a2 [page] [4B]`                | write one page. DESTRUCTIVE|
| 0x55 | N2_GET_INFO    | `55`                            | active slot, bank cnt, button, FW ver |
| 0x43 | N2_GET_ID      | `43`                            | 16-byte device ID          |
| 0xA9 | N2_SET_BANK_CNT| `a9 [count]`                    | DESTRUCTIVE-ish            |
| 0x3B | N2_FAST_READ   | `3b [start] [end] [bank]`       | read pages [start..end] of a bank |
| 0xA5 | N2_WRITE       | `a5 [page] [bank] [4B]`         | DESTRUCTIVE                |
| 0xAE | N2_FAST_WRITE  | `ae [start] [bank] [size] [..]` | DESTRUCTIVE                |
| 0x46 | N2_LOCK        | `46`                            | -> 0x0a                    |
| 0x44 | N2_UNLOCK_PREP | `44`                            |                            |
| 0x45 | N2_UNLOCK_FIN  | `45`                            | after physical button press|
| 0xA7 | N2_SELECT_BANK | `a7 [bank]`                     | -> 0x0a                    |

### Bank dump (`dumpBank`) — CONFIRMED
For each bank: loop page 0 → 0x8E in steps of 15 (start → start+14 inclusive),
sending `3B, page, min(0x8E, page+14), bank`, concatenating the 4-byte pages.
**A full bank dump = 0x23C = 572 bytes** (143 pages × 4). Pages 0x87–0x8E hold the
32-byte ECC signature block. (An amiibo .bin as used by TagMo is 540 bytes / 135 pages.)

## 4. Amiibo crypto (NTAG215 dump)
AES-128-CTR + HMAC-SHA256, keys derived from user `key_retail.bin`
(unfixed-info + locked-secret). Port socram8888/amiitool. Never ship keys.

## Deliberately OMITTED from our port (privacy/offline)
The official app made RestEase web calls (`n2elite/cheats`, `n2elite/file/randomize`,
statue downloads). We implement NONE of these — the app is fully offline.
