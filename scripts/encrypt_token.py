#!/usr/bin/env python3
"""
Generate a Fernet key and encrypt a token.
"""

import argparse
import os
from pathlib import Path

from cryptography.fernet import Fernet


def main() -> int:
    parser = argparse.ArgumentParser(description="Encrypt token with Fernet")
    parser.add_argument("--key-file", required=True)
    parser.add_argument("--token-file", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    key_path = Path(args.key_file)
    token_path = Path(args.token_file)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.parent.mkdir(parents=True, exist_ok=True)

    key = Fernet.generate_key()
    key_path.write_bytes(key)
    os.chmod(key_path, 0o600)

    encrypted = Fernet(key).encrypt(args.token.encode("utf-8"))
    token_path.write_bytes(encrypted)
    os.chmod(token_path, 0o600)

    print(f"Key: {key_path}")
    print(f"Encrypted token: {token_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
