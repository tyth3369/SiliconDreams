# Third-party frontend assets

SiliconDreams vendors the following browser assets so the production UI does not depend on runtime CDNs. The files are served unchanged from `static/vendor/` or `static/fonts/`.

| Component | Version | License | Vendored files | SHA-256 |
|---|---:|---|---|---|
| HTMX | 1.9.12 | 0BSD | `static/vendor/htmx-1.9.12.min.js` | `449317ade7881e949510db614991e195c3a099c4c791c24dacec55f9f4a2a452` |
| Marked | 15.0.12 | MIT | `static/vendor/marked-15.0.12.min.js` | `3e7e7d7feb3e5d58cb6c804f68ab5c24cc7e5eb6270fd6e5cbb9124739217d0c` |
| DOMPurify | 3.4.15 | MPL-2.0 OR Apache-2.0 | `static/vendor/dompurify-3.4.15.min.js` | `f263b05369e050fa175d4ecb9c9358eb4253602d510297adfb31df48b2f1c4d5` |
| IBM Plex Mono | 5.3.0 package | OFL-1.1 | Latin WOFF2, weights 400/500/600 | See files in `static/fonts/` |
| IBM Plex Sans | 5.3.0 package | OFL-1.1 | Latin WOFF2, weights 300/400/500/600 | See files in `static/fonts/` |

The corresponding license texts are preserved under `static/vendor/licenses/`. Project source code remains licensed under the repository [LICENSE](LICENSE).

