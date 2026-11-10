# Third-party components

This is a review package, not a completed redistribution clearance.

| Component | Version | Evidence / terms |
|---|---|---|
| Python | 3.13.17 | PSF license and bundled dependency notices |
| PySide6 / Qt / Shiboken | 6.12.0 | LGPL/GPL alternatives in wheel metadata; individual Qt modules and bundled third-party libraries have their own terms |
| Qt PDF wheel | 6.12.0.140 | Exact original build dependency; separate module/source/notice review remains |
| PyInstaller | 6.22.3 | GPL with bootloader exception, see included COPYING |
| Inno Setup | 7.1.1 | Compiler/runtime license retained in licenses/Inno-Setup.txt |
| OpenAI atlas validator | pinned upstream commit in vendor/provenance.json | Apache-2.0; vendor/NOTICE.md and vendor/LICENSE.txt |

The original Windows archive contains OpenSSL and additional Qt third-party code. Exact notices and corresponding sources must be completed before public binary release. Files under licenses are evidence collected from exact package versions, not a grant of a commercial Qt license.

Qt DLLs remain separate and replaceable in the onedir layout. Do not use an installer license that forbids rights required by the relevant open-source licenses. Character artwork is excluded from all software license claims.
