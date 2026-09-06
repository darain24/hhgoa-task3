"""Canonical SHA-256 records and zero-value Polygon Amoy self-transactions."""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from web3 import Web3
from web3.exceptions import Web3Exception
from web3.middleware import ExtraDataToPOAMiddleware

from config.settings import OUTPUT_DIR, require_env


class BlockchainError(Exception):
    """Configuration, transaction, or verification failed."""


def compute_record_hash(record: dict[str, Any]) -> str:
    """Return 0x-prefixed SHA-256 of canonical JSON; raise BlockchainError if invalid."""
    try:
        canonical = json.dumps(
            record, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError):
        raise BlockchainError(
            "Record must contain finite, JSON-serializable values."
        ) from None
    return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_hash(value: str) -> None:
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", value):
        raise BlockchainError("Expected a 0x-prefixed, 32-byte hex hash.")


def _connect() -> Web3:
    rpc = require_env("POLYGON_AMOY_RPC_URL")
    if not rpc.startswith(("https://", "http://")):
        raise ValueError("POLYGON_AMOY_RPC_URL must be an HTTP(S) endpoint.")
    client = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 30}))
    client.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    if client.eth.chain_id != 80002:
        raise BlockchainError("RPC must be Polygon Amoy (chain ID 80002).")
    return client


def check_chain_ready() -> None:
    """Validate Amoy, signing account and balance before work; raise BlockchainError."""
    try:
        client = _connect()
        address = Web3.to_checksum_address(require_env("WALLET_ADDRESS"))
        account = client.eth.account.from_key(require_env("WALLET_PRIVATE_KEY"))
        if account.address != address:
            raise BlockchainError("WALLET_ADDRESS does not match the private key.")
        if client.eth.get_balance(address) == 0:
            raise BlockchainError("Fund the test wallet with Amoy faucet POL first.")
    except (ValueError, Web3Exception, requests.RequestException):
        raise BlockchainError(
            "Check Amoy RPC, wallet configuration and connection."
        ) from None


def upload_hash_to_chain(hash_hex: str) -> dict[str, Any]:
    """Confirm a zero-value Amoy self-transaction and return receipt; raise BlockchainError."""
    _validate_hash(hash_hex)
    tx_hash: str | None = None
    try:
        client = _connect()
        address = Web3.to_checksum_address(require_env("WALLET_ADDRESS"))
        account = client.eth.account.from_key(require_env("WALLET_PRIVATE_KEY"))
        if account.address != address:
            raise BlockchainError("WALLET_ADDRESS does not match the private key.")
        if client.eth.get_code(address):
            raise BlockchainError(
                "Use a dedicated ordinary test wallet without account code."
            )
        transaction = {
            "chainId": 80002,
            "from": address,
            "to": address,
            "value": 0,
            "data": hash_hex,
            "nonce": client.eth.get_transaction_count(address, "pending"),
            "gasPrice": client.eth.gas_price,
        }
        transaction["gas"] = (client.eth.estimate_gas(transaction) * 120 + 99) // 100
        if (
            client.eth.get_balance(address)
            < transaction["gas"] * transaction["gasPrice"]
        ):
            raise BlockchainError("Insufficient Amoy POL for the transaction fee.")
        signed = account.sign_transaction(transaction)
        # Compute and persist the identifier before submission: an RPC timeout may
        # occur after broadcast, so the user must be able to look up this transaction.
        tx_hash = Web3.to_hex(signed.hash)
        pending = {
            "record_hash": hash_hex,
            "tx_hash": tx_hash,
            "network": "polygon-amoy-testnet",
            "block_number": None,
            "explorer_url": f"https://amoy.polygonscan.com/tx/{tx_hash}",
            "timestamp": datetime.now(timezone.utc)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z"),
            "verified": False,
        }
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        (OUTPUT_DIR / "tx_receipt.json").write_text(
            json.dumps(pending, indent=2) + "\n"
        )
        print(f"Transaction ID: {tx_hash}", flush=True)
        client.eth.send_raw_transaction(signed.raw_transaction)
        receipt = client.eth.wait_for_transaction_receipt(
            tx_hash, timeout=180, poll_latency=2
        )
        if receipt["status"] != 1:
            raise BlockchainError(f"Transaction failed on-chain: {tx_hash}")
        pending["block_number"] = receipt["blockNumber"]
        (OUTPUT_DIR / "tx_receipt.json").write_text(
            json.dumps(pending, indent=2) + "\n"
        )
        return pending
    except (ValueError, Web3Exception, requests.RequestException, OSError):
        suffix = f" Check {tx_hash} before sending again." if tx_hash else ""
        raise BlockchainError(
            "Transaction failed or confirmation is unavailable; check RPC, wallet and outputs/."
            + suffix
        ) from None


def verify_hash_on_chain(tx_hash: str, expected_hash_hex: str) -> bool:
    """Fetch confirmed successful Amoy transaction and compare calldata; raise BlockchainError."""
    _validate_hash(tx_hash)
    _validate_hash(expected_hash_hex)
    try:
        client = _connect()
        transaction = client.eth.get_transaction(tx_hash)
        receipt = client.eth.get_transaction_receipt(tx_hash)
        if transaction["blockNumber"] is None or receipt["status"] != 1:
            raise BlockchainError("Transaction is not successfully confirmed.")
        block = client.eth.get_block(receipt["blockNumber"])
        if block["hash"] != receipt["blockHash"]:
            raise BlockchainError(
                "Transaction is no longer in the canonical chain; verify again."
            )
        return bytes(transaction["input"]) == bytes.fromhex(expected_hash_hex[2:])
    except (ValueError, Web3Exception, requests.RequestException):
        raise BlockchainError(
            "Cannot fetch confirmed transaction; check RPC and transaction ID."
        ) from None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Manual blockchain check (spends faucet POL)."
    )
    parser.add_argument("--self-test", required=True, action="store_true")
    parser.parse_args()
    try:
        record = {"purpose": "manual hash integrity check"}
        digest = compute_record_hash(record)
        receipt = upload_hash_to_chain(digest)
        verified = verify_hash_on_chain(receipt["tx_hash"], digest)
        altered = verify_hash_on_chain(
            receipt["tx_hash"], compute_record_hash({"purpose": "altered"})
        )
        receipt["verified"] = verified
        (OUTPUT_DIR / "tx_receipt.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
        print(
            f"Original verified: {str(verified).lower()}; altered verified: {str(altered).lower()}"
        )
        sys.exit(0 if verified and not altered else 1)
    except (BlockchainError, OSError) as error:
        print(f"Error [blockchain]: {error}", file=sys.stderr)
        sys.exit(1)
