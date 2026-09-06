"""CLI for local face presence, supplied-post retrieval and on-chain integrity."""

import argparse
import json
import sys
from pathlib import Path

from config.settings import OUTPUT_DIR
from src.blockchain import (
    BlockchainError,
    check_chain_ready,
    compute_record_hash,
    upload_hash_to_chain,
    verify_hash_on_chain,
)
from src.face_detect import FaceNotDetectedError, detect_face
from src.web_search import SearchAPIError, fetch_known_post


def run_pipeline(image_path: str, post_url: str) -> None:
    """Run the three stages and persist a verifiable record; propagate stage errors."""
    if not Path(image_path).is_file():
        raise FaceNotDetectedError("Provide a readable local image file.")
    print("Checking Amoy RPC and test wallet…", flush=True)
    check_chain_ready()
    print(
        "[1/4] Detecting a face locally (first run may download model weights)…",
        flush=True,
    )
    face = detect_face(image_path)
    print(f"[1/4] Face detected — confidence: {face['confidence']:.4f}", flush=True)
    print("[2/4] Fetching the user-provided URL live…", flush=True)
    evidence = fetch_known_post(post_url)
    selected = evidence["selected_match"]
    print(f"[2/4] Supplied page retrieved — {selected['url']}", flush=True)
    print("URL supplied by user; identity relationship is not verified.", flush=True)
    record = {
        "source_image_sha256": face["source_image_sha256"],
        "matched_url": selected["url"],
        "matched_domain": selected["source_domain"],
        "match_rank": 1,
        "detection_model": face["detector"],
        "recognition_model": None,
        "timestamp": evidence["query_timestamp"],
        "selection_method": "user_provided_url",
        "page_content_sha256": selected["page_content_sha256"],
    }
    # Persist the exact preimage before any irreversible chain write.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "record.json").write_text(json.dumps(record, indent=2) + "\n")
    digest = compute_record_hash(record)
    print(f"[3/4] Record hash — {digest}", flush=True)
    print(
        "[4/4] Sending hash to Polygon Amoy and waiting for confirmation…", flush=True
    )
    receipt = upload_hash_to_chain(digest)
    verified = verify_hash_on_chain(receipt["tx_hash"], digest)
    receipt["verified"] = verified
    (OUTPUT_DIR / "tx_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Explorer: {receipt['explorer_url']}", flush=True)
    print(f"Hash verified on-chain: {str(verified).lower()}", flush=True)
    if not verified:
        raise BlockchainError("On-chain calldata does not match the local record.")


def main() -> int:
    """Parse CLI arguments, display clean stage errors and return a process status."""
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--image", help="Path to a local single-face photo")
    modes.add_argument("--verify", nargs=2, metavar=("TX_HASH", "EXPECTED_HASH"))
    modes.add_argument("--verify-record", nargs=2, metavar=("TX_HASH", "RECORD_JSON"))
    parser.add_argument("--post-url", help="Known public post URL you provide")
    args = parser.parse_args()
    if args.image and not args.post_url:
        parser.error("--image requires --post-url")
    if not args.image and args.post_url:
        parser.error("--post-url is only valid with --image")
    try:
        if args.image:
            run_pipeline(args.image, args.post_url)
        else:
            if args.verify_record:
                tx_hash, record_path = args.verify_record
                record = json.loads(Path(record_path).read_text())
                if not isinstance(record, dict):
                    raise ValueError("Record must be a JSON object.")
                expected = compute_record_hash(record)
                print(f"Recomputed record hash: {expected}")
            else:
                tx_hash, expected = args.verify
            verified = verify_hash_on_chain(tx_hash, expected)
            print(f"Hash verified on-chain: {str(verified).lower()}")
            return 0 if verified else 1
    except FaceNotDetectedError as error:
        print(f"Error [face]: {error}", file=sys.stderr)
        return 1
    except SearchAPIError as error:
        print(f"Error [retrieval]: {error}", file=sys.stderr)
        return 1
    except BlockchainError as error:
        print(f"Error [blockchain]: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print(
            "Error [input/output]: Check input JSON, configuration and file permissions.",
            file=sys.stderr,
        )
        return 1
    except Exception as error:  # noqa: BLE001 — CLI boundary must not expose secrets in tracebacks.
        print(
            f"Error: {type(error).__name__}; check dependencies, model weights and configuration.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
