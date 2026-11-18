# Third-Party Notices

## SearXNG

- Project: SearXNG
- Source: https://github.com/searxng/searxng
- Integrated revision: `c360868e5b7c01e463a362a53518190d5a3b1097`
- Container image: `docker.io/searxng/searxng@sha256:268a4b460136dcefc8f2e896b6098ba3f770c8218dbbddcb86811b06b06816f1`
- License: GNU Affero General Public License v3.0 or later (AGPL-3.0-or-later)
- Integration note: the upstream image is used unmodified; this project supplies deployment and runtime configuration only.

This project includes code and implementation ideas derived from nanobot.

## nanobot

- Project: nanobot
- Source: https://github.com/HKUDS/nanobot
- Bundled reference license: `reference/nanobot-main/LICENSE`
- License: MIT

MIT License

Copyright (c) 2025-present Xubin Ren and the nanobot contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## open-websearch

- Project: open-websearch
- Version: 2.2.0-compatible container image
- Source: https://github.com/aas-ee/open-websearch
- Container image: `ghcr.io/aas-ee/open-web-search`
- Bundled reference license: `reference/open-webSearch-main/LICENSE`
- License: Apache License 2.0
- Usage: separately deployed search daemon accessed through its documented HTTP API; upstream source is retained only as a reference copy.

The full Apache License 2.0 text is available in the bundled reference license above and at
https://www.apache.org/licenses/LICENSE-2.0.

## Scrapling

- Project: Scrapling
- Version: `>=0.5,<0.6`
- Source: https://github.com/D4Vinci/Scrapling
- License: BSD 3-Clause License
- Usage: the lightweight HTTP `Fetcher` enriches a bounded set of Open WebSearch and SearXNG results
  with safe redirect resolution, browser-TLS impersonation and cleaned main-content extraction. A
  single-result Chromium stealth fallback is enabled only for detected challenge or dynamic-shell pages;
  it is time-bounded, preserves the original snippet on failure, and does not expose a new Agent API.

The upstream package retains its BSD-3-Clause license metadata and notice in the installed distribution.

## Docling

- Project: Docling
- Package: `docling-slim==2.122.0`
- Source: https://github.com/docling-project/docling
- License: MIT
- Incorporated into: the local `docling_pdf` adapter through Docling Slim's
  `PyPdfiumDocumentBackend`; no complete Docling model pipeline or remote service is embedded.
- Modification note: this project supplies its own conservative reading-order, table/formula
  classification, character-span and fallback orchestration around the upstream PDF backend.

The upstream package retains its MIT license metadata and notices in the installed distribution.

## LightRAG

- Project: LightRAG
- Source: https://github.com/HKUDS/LightRAG
- Reviewed revision: `aaebfe1bb8d55deb6a4304d357a3bf4c92fcd40a`
- License: MIT
- Incorporated into: the first-class `lightrag_primary` pipeline and the optional
  `hybrid_v2.llm_enhancement` orchestration. The project-specific implementation adopts the upstream
  ideas of LLM-driven entity/relation extraction, bounded continuation/gleaning, dual-level graph and
  vector retrieval (`naive`/`local`/`global`/`hybrid`/`mix`), asynchronous bounded fan-out, incremental
  graph merging and pre-persistence quality filtering.
- Integration boundary: LightRAG is not installed as a second graph runtime and does not own project
  data. PostgreSQL remains authoritative; Neo4j and Milvus remain rebuildable projections. Prompts,
  defense ontology enforcement, exact character-span reconstruction, OCR repair proposals,
  cross-document evidence governance, multi-hop innovation discovery and review governance are
  project-specific implementations. `lightrag_primary` uses the model selected in project settings and
  does not start a bundled local model or any information-extraction sidecar.

MIT License

Copyright (c) 2025 LightRAG Team

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## BGE-M3 and Sentence Transformers

- Model: BAAI/bge-m3
- Source: https://huggingface.co/BAAI/bge-m3
- Integrated revision: `5617a9f61b028005a4858fdac845db406aefb181`
- Model license: MIT
- Runtime: Sentence Transformers 5.1.2
- Runtime source: https://github.com/huggingface/sentence-transformers
- Runtime license: Apache License 2.0
- Incorporated into: `services/local_embedding` as an isolated, local-only embedding sidecar.
- Data boundary: model weights are downloaded from Hugging Face; Pilot document text is sent only
  over the local Docker network to the sidecar and is not sent to the model repository or an external API.

## Yuxi

- Project: Yuxi
- Version: v0.7.3
- Upstream `main` commit used for README capability alignment: `23576378fb22bed5c5373a4223e1948327dab157`
- Source: https://github.com/xerrors/Yuxi
- Bundled reference license: `reference/Yuxi-main/LICENSE`
- License: MIT
- Incorporated into: `backend/package/platform_core` (Python distribution `platform-core`), together with portions of `backend/server`、`web/`、`docker/` and `compose.yaml`. This is license attribution only. The product name is「装备智能研究平台」.

MIT License

Copyright (c) 2025 Yuxi Project Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
