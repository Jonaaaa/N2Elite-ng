N2Elite-ng — macOS distribution

Original application by Jona: https://github.com/Jonaaaa/N2Elite-ng
macOS packaging maintained in: https://github.com/lanxinger/N2Elite-ng
Downloads: https://github.com/lanxinger/N2Elite-ng/releases/latest

INSTALL
1. Choose the ZIP for your Mac: arm64 for Apple silicon (M1 and newer), or
   x86_64 for Intel. Extract it and drag N2Elite-ng.app to Applications.
2. Open N2Elite-ng.app. Python, Tcl/Tk, serial support, cryptography, and the
   offline name database are included; no Python installation is needed.
3. Plug in your N2 Elite reader, select its serial port, and click Connect.

FIRST LAUNCH
These builds are ad-hoc signed and are not Apple-notarized. macOS may block
the first launch. Follow Apple's instructions to allow a trusted app in
System Settings > Privacy & Security:
https://support.apple.com/102445
Keep macOS security protections enabled. If your Mac is managed and does
not allow an exception, ask your administrator or build from source.

COMMAND LINE
In Terminal, change to the extracted folder and run:
  ./n2elite-ng-cli --help
  ./n2elite-ng-cli ports

CHECKSUM
SHA256SUMS.txt is attached to the GitHub release. Place it next to the
downloaded ZIP and verify with:
  shasum -a 256 --ignore-missing -c SHA256SUMS.txt

TESTING
CI runs the upstream offline tests, checks app startup, and tests the frozen
CLI's crypto round-trip and bundled database using synthetic data.
These checks do not verify physical device writes or bank management.
No Nintendo keys or personal amiibo dumps are included.

CREDITS AND LICENSES
The original application and credits are preserved. This fork adds native
macOS packaging, build/run scripts, and macOS CI/release automation.
See LICENSE, THIRD_PARTY_NOTICES.md, and licenses/ for terms and credits.
SOURCE-COMMIT.txt identifies the source commit used for this package.
