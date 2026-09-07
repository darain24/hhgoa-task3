# Face & Post Record — Polygon Amoy

A small Python CLI that detects one face locally with RetinaFace, retrieves a
**known post URL supplied by the user** over HTTP, hashes a canonical record, and
anchors its 32-byte SHA-256 digest in a zero-value Polygon Amoy self-transaction.
A separate command re-fetches the confirmed transaction and compares the hash.

This is the revised scope agreed with the project owner. It does **not** search
for a person, produce recognition embeddings, or verify that a photo and post
refer to the same person. Detection confidence measures face presence only.

## Relationship to the supplied specification

| Original requirement | This implementation |
| --- | --- |
| CLI with three stage modules, no frontend | Preserved |
| RetinaFace via DeepFace | Preserved, detection only |
| ArcFace embeddings | Removed; no identification is performed |
| Live SerpApi face/reverse-image search | Replaced by a live GET of `--post-url`; no SerpApi key needed |
| Rank and social-domain match selection | One user-supplied URL, rank 1; no inferred match |
| Canonical JSON SHA-256 | Preserved; explicit selection method and fetched-content hash added |
| Polygon Amoy calldata and independent verification | Preserved |
| Local manual module checks | Preserved; no test framework or web service |

The original face-to-web search acceptance criterion is not met by this revised
scope. Explain the adaptation to evaluators before relying on it for submission.

## Setup

Use **Python 3.12** (validated dependency environment: macOS Apple Silicon).
TensorFlow is a large download; installation and the first model download can
exceed five minutes. Python 3.14 is not supported by these pins.

```sh
git clone https://github.com/darain24/hhgoa-task3.git
cd hhgoa-task3
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

The repository is private; cloning requires GitHub access (use `gh auth login`
and `gh auth setup-git` if needed). Reviewers must be granted access before
submission.

Edit `.env` locally:

- `POLYGON_AMOY_RPC_URL`: your provider's Amoy HTTP(S) RPC endpoint.
- `WALLET_PRIVATE_KEY`: a dedicated test-only wallet private key.
- `WALLET_ADDRESS`: the corresponding address, funded with faucet **POL**.
- `SERPAPI_KEY`: optional, unused placeholder retained at the project owner’s
  request. Leave it blank; setting it does not enable search.

Never use a wallet that holds assets of value. The code checks chain ID **80002**,
key/address consistency, estimated fees, transaction success and confirmation.
Read-only verification needs only the RPC setting, not a private key.

Network details and faucet options:
[Polygon RPC reference](https://docs.polygon.technology/pos/reference/rpc-endpoints),
[Polygon faucet documentation](https://docs.polygon.technology/tools/gas/matic-faucet).
Provider availability and faucet access can change. No paid API is required;
choose a free RPC plan and use test tokens only.

The repository includes the attributed public-domain portrait
`test_images/barack_obama.jpg` for the known-source demo below. Personal
participant photos, including the locally tested `test_images/sample_face.jpg`,
are excluded from Git. To test your own photo, supply a local path and a known
public page URL.

## Run

```sh
python pipeline.py --image test_images/barack_obama.jpg --post-url 'https://commons.wikimedia.org/wiki/File:President_Barack_Obama.jpg'
```

For your own input, replace both the image path and URL. The photo is processed locally
and is never uploaded. The first detection run downloads RetinaFace weights to
DeepFace's cache (usually `~/.deepface/weights/`). A network connection is needed
for that initial download, page retrieval and blockchain operations.

The terminal prints detection confidence, the supplied page URL, the record hash,
the transaction ID, explorer link and `Hash verified on-chain: true` only after
successful re-fetching. Exit status is nonzero on errors or mismatches. HTTP
errors, empty pages and non-HTML responses fail; there is no cached-search fallback.

## Independent verification

```sh
python pipeline.py --verify 0xYOUR_TRANSACTION_HASH 0xYOUR_RECORD_HASH
python pipeline.py --verify-record 0xYOUR_TRANSACTION_HASH outputs/record.json
```

Use the full 66-character hexadecimal values printed by the pipeline. The second
command recomputes the digest from the saved record; changing any hashed field
makes comparison return `false`. The transaction ID alone locates the on-chain
digest, but an expected hash or original record is needed to test integrity.
No photo, wallet key or URL fetch is required for either verification command.

Open the printed [Amoy PolygonScan](https://amoy.polygonscan.com/) transaction
link, expand its input data and inspect the raw hex. It is the 32-byte record
hash, not the JSON itself. One successful inclusion is checked, not long-term
finality; re-verify later if needed.

## Outputs and canonical record

Each run writes local, gitignored evidence in `outputs/`:

- `search_results.json`: retrieval time, provided and final URLs, title, HTTP
  status and selected entry; filename retained from the original architecture.
- `record.json`: the exact hash preimage, written before submitting a transaction.
- `tx_receipt.json`: transaction ID, record hash, network, block, explorer link,
  local submission timestamp and verification result. Saved before broadcast to
  preserve the transaction ID even when the RPC times out.

Copy a completed run's files elsewhere before running again: these filenames are
overwritten. If submission or confirmation times out, inspect the printed
transaction ID before rerunning to avoid creating an additional transaction.

```json
{
  "source_image_sha256": "SHA-256 of exact input bytes, without 0x",
  "matched_url": "https://the-final-fetched-url.example/post",
  "matched_domain": "the-final-fetched-url.example",
  "match_rank": 1,
  "detection_model": "RetinaFace",
  "recognition_model": null,
  "timestamp": "2026-09-05T14:32:10Z",
  "selection_method": "user_provided_url",
  "page_content_sha256": "SHA-256 of HTTP response body bytes after transfer decoding"
}
```

The `matched_*` names are retained for compatibility; they describe the supplied
page, not a verified face match. Hashing is precisely
`SHA256(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8"))`,
returned as a `0x`-prefixed digest. Default JSON ASCII escaping is used. The same
record hashes identically; separate runs can differ because timestamp and live
page content change. No embeddings, face crops or raw page content are saved.

## Manual checks

Run modules from the repository root using Python's `-m` mode:

```sh
python -m src.face_detect test_images/barack_obama.jpg
python -m src.web_search 'https://commons.wikimedia.org/wiki/File:President_Barack_Obama.jpg'
python -m src.blockchain --self-test
```

The blockchain check sends one transaction using faucet POL, then verifies both
the original record (`true`) and an altered record (`false`). It overwrites the
receipt output, so run it before the final demo. It is separate from the real
pipeline; its dummy record is never used by `pipeline.py`.

Before recording, run the full CLI twice successfully. Save the final outputs,
re-verify `record.json`, then copy it and change `matched_url` to confirm that
`--verify-record` exits 1 and prints `false`. Also check a no-face image, a missing
image, a missing configuration value, and an inaccessible URL for clear failures.

## Recording and submission

1. Finish the manual checks with your photo, known post and funded test wallet.
2. In a clean terminal, run the full CLI and show all four stages without cuts.
3. Run `--verify-record` and open the transaction in PolygonScan in the same take.
4. Watch the recording in full; ensure no `.env` content or private key appears.
5. Publish source and the approved sample photo to a reviewer-accessible GitHub
   repository, upload the recording, and submit those links using the form from
   the supplied PRD. The documents specify September 7, 2026, 11:59 PM and no
   resubmissions; confirm the applicable timezone with the organizers.

The source repository and real Amoy transaction evidence are available; an
unedited screen recording and form submission are separate deliverables.
For private repository submission, grant the evaluator access before sending
the link. No evaluator account was supplied, so collaborator access has not
been configured.

## Limitations

This shortlisting proof of concept is not for locating or surveilling people.
Use your own photo or a consenting participant's photo. Only single-face images
are accepted. It does not establish identity, ownership, authorship or consent.

A successful HTTP response proves retrieval, not that a social site's post was
accessible: login, bot-challenge and consent pages sometimes return HTTP 200.
Inspect the final URL and title manually. Private posts and JavaScript-only sites
may be unsuitable. Retrieval follows redirects and limits decoded bodies to
5 MiB; it does not browse a logged-in session or discover additional URLs.

Blockchain anchoring proves that the recorded digest was included in a block; it
does not prove that the underlying claims are true. Only the digest is public on
chain. Keep the exact record to verify it later. The fetched body digest commits
to the received representation, but raw content is not archived, and later live
fetches may differ. Local timestamps are client-reported; block inclusion supplies
the independent chain timing.

Implementation references:
[DeepFace detection API](https://github.com/serengil/deepface),
[web3.py transactions](https://web3py.readthedocs.io/en/v7.16.0/transactions.html).

## Validation in this workspace

- Python 3.12 dependency installation, dependency compatibility, DeepFace/web3
  imports, source compilation and Ruff checks passed.
- A real HTTP fetch of `https://example.com` returned its page title and content
  digest. This was a retrieval smoke check, not a participant post demo.
- RetinaFace weights downloaded and a blank image was rejected.
- Isolated checks exercised deterministic hashing, record tampering, failed
  transaction rejection, signing, insufficient balance, orchestration, invalid
  CLI inputs, URL validation and response-size limits. RPC behavior was mocked
  only inside those temporary checks; the shipped pipeline uses real RPC calls.
- Phase 0 completed on September 6, 2026: a dedicated test wallet was generated
  locally, the Amoy RPC was verified as chain 80002, key/address consistency
  passed, and 0.01 faucet POL was received and confirmed through the RPC. The
  private key is stored only in the ignored `.env`, with owner-only permissions.
- Phase 3 passed on September 6, 2026 using a real Amoy transaction: original
  record verification returned `true`, altered record verification returned
  `false`, and the separate `--verify-record` CLI command passed.
  [View the self-test transaction](https://amoy.polygonscan.com/tx/0x50925f81f0539820c272c37bcbe0dc37ac1c5e4d1d279f5b415e2e014e3dec1a).
  The retained self-test record and receipt are in `outputs/blockchain_selftest_*.json`.
- Phase 1 passed on September 6, 2026 using the owner-supplied
  `test_images/sample_face.jpg`: exactly one face, RetinaFace confidence 1.0.
  Bounding box: x=441, y=494, width=162, height=203. Evidence is saved locally
  in `outputs/face_detection.json`. Confidence is face presence, not identity.
- Phases 2 and 4 passed on September 6, 2026 for the revised known-source
  public-figure demo below: local detection, live source-page retrieval, real
  Amoy hash storage and independent verification all succeeded. Altering the
  saved record made CLI verification return `false` with exit status 1.
- Phase 5: source, pinned dependencies, configuration example and attributed
  demo photo are published in the private repository at
  [darain24/hhgoa-task3](https://github.com/darain24/hhgoa-task3). Personal photos,
  secrets, virtual environments and local run outputs are excluded.
- Phase 6 passed on September 7, 2026: cloned the private GitHub repository at
  commit `eca7b97`, installed requirements with pip in a fresh Python 3.12 venv,
  downloaded RetinaFace into an empty model cache, and completed the live demo
  on macOS Apple Silicon. `pip check` passed. Both standalone verification
  commands passed with only RPC configuration; an altered record returned
  `false` and exit status 1. No application code fixes were needed.
  [Fresh-clone transaction](https://amoy.polygonscan.com/tx/0x4a8a687f517417fbf958e6ceacbe310781503fc40f72bb8cea5aa48bbe78d2e6).
  Local logs and receipts are saved in `outputs/phase6/`; these are not bundled
  in Git. The check used the same host, existing GitHub authorization and a
  locally supplied funded test wallet; it is not a cross-platform validation.
- Recording and submission remain outstanding. This demo does not validate the original face-search requirement.


## Reproducible public-figure demo

At the project owner’s request, an additional demo uses
`test_images/barack_obama.jpg`: Barack Obama’s official December 6, 2012
portrait, photographed by Pete Souza for the White House.
[Source and public-domain notice](https://commons.wikimedia.org/wiki/File:President_Barack_Obama.jpg).
The original JPEG was downloaded without modification. This is a known-source
detection/integrity test, not face-based identification or search. It is an
explicit adaptation of the original own-face/consenting-participant demo scope;
public-domain copyright status is not a claim of personal consent.

```sh
python pipeline.py --image test_images/barack_obama.jpg --post-url 'https://commons.wikimedia.org/wiki/File:President_Barack_Obama.jpg'
```

The recorded terminal run detected one face with confidence 1.0000, retrieved
the source page live and printed `Hash verified on-chain: true`.

[Successful Amoy transaction](https://amoy.polygonscan.com/tx/0x01ffcf39d53802611e7a638606458eeabfc7635c0e8579d4dee1bb1f7396c5b7).

Local evidence: `outputs/celebrity_demo.log`, `outputs/celebrity_record.json`,
`outputs/celebrity_search_results.json`, `outputs/celebrity_tx_receipt.json` and
`outputs/celebrity_verification.log`. The log is terminal evidence, not the
required screen recording.
