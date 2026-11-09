Native macOS packages for N2Elite-ng, the N2 Elite / Amiiqo manager by
[Jona](https://github.com/Jonaaaa/N2Elite-ng).

- **Apple silicon (M1 and newer):** download `N2Elite-ng-macOS-arm64.zip`.
- **Intel Macs:** download `N2Elite-ng-macOS-x86_64.zip`.

Each ZIP includes a double-clickable `.app`, a standalone CLI, the offline
amiibo name database, usage instructions, source commit, and license notices.
Python and Tcl/Tk are bundled. Drag the extracted `.app` to Applications.

These builds are **ad-hoc signed and not Apple-notarized**. macOS may require
a first-launch exception; see [Apple's instructions](https://support.apple.com/102445).
Checksums are attached in `SHA256SUMS.txt`.

The macOS workflow builds both architectures on GitHub runners, runs the
upstream offline tests, checks GUI startup, and tests the packaged CLI's crypto
round-trip and database lookup with synthetic data. Device writes and bank
management are not covered by those tests.

This fork adds macOS packaging and build/release automation. Original credits
and the upstream `LICENSE` are retained. No Nintendo keys or personal dumps
are included. See the repository for source and rebuild instructions.
