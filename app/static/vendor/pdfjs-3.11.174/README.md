# pdf.js 3.11.174 (vendored)

The two files the PDF quick-view drawer (`app/static/docview.js`) needs, served
from this machine so the drawer works offline and the app makes no request to
a CDN.

- Source: https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/
- Checked on 2026-11-14 against cdnjs's published SHA-512 values:
  - `pdf.min.js` sha512-q+4liFwdPC/bNdhUpZx6aXDx/h77yEQtn4I1slHydcbZK34nLaR3cAeYSJshoxIOq3mjEf7xJE8YWIUHMn+oCQ==
  - `pdf.worker.min.js` sha512-BbrZ76UNZq5BhH7LL7pn9A4TKQpQeNCHOo65/akfelcIBbcVvYWOFQKPXIrykE3qZxYjmDX573oa4Ywsc7rpTw==
- Licence: Apache-2.0, Mozilla (header inside each file).

Stay on 3.x: 4.x and later ship ES modules only, which a plain `<script>`
cannot load (see BUILD.md, "What is still open"). The version is in the folder
name, so the browser may cache these files for good.
