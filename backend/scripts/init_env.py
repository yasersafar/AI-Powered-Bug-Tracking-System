"""Create or complete the local `.env` with per-installation secrets (stdlib only).

Usage:  python3 backend/scripts/init_env.py [path/to/.env]

* copies .env.example when .env does not exist
* replaces placeholder values and adds missing generated keys, never overwriting real values:
  JWT_SECRET_KEY, NTFY_PUBLISH_TOKEN, NTFY_PUBLISHER_HASH, SEED_PASSWORD
"""

import re
import secrets
import shutil
import string
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLACEHOLDERS = {"", "replace-with-a-long-random-string", "change-me", "generated-by-make-env"}
BCRYPT_ALPHABET = "./" + string.ascii_letters + string.digits


def _ntfy_token() -> str:
    # Same shape as `ntfy token generate`: "tk_" + 29 lowercase letters/digits.
    alphabet = string.ascii_lowercase + string.digits
    return "tk_" + "".join(secrets.choice(alphabet) for _ in range(29))


def _unusable_bcrypt_hash() -> str:
    # A well-formed bcrypt string that matches no known password: the publisher account can
    # only authenticate with its access token, never with a password.
    body = "".join(secrets.choice(BCRYPT_ALPHABET) for _ in range(53))
    return f"'$2a$10${body}'"  # single quotes: Compose must not interpolate the $ signs


def _seed_password() -> str:
    # Satisfies FR-01 (upper, lower, digit, special) and stays easy to type in a demo.
    return "Demo#" + secrets.token_hex(3).upper() + "a1"


GENERATORS: dict[str, Callable[[], str]] = {
    "JWT_SECRET_KEY": lambda: secrets.token_urlsafe(48),
    "NTFY_PUBLISH_TOKEN": _ntfy_token,
    "NTFY_PUBLISHER_HASH": _unusable_bcrypt_hash,
    "SEED_PASSWORD": _seed_password,
}


def main(env_path: Path) -> None:
    if not env_path.exists():
        shutil.copy(ROOT / ".env.example", env_path)
        print(f"Created {env_path.name} from .env.example")
    lines = env_path.read_text().splitlines()
    present: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^([A-Z0-9_]+)=(.*)$", line)
        if match:
            present[match.group(1)] = index

    changed = []
    for key, generate in GENERATORS.items():
        if key in present:
            current = lines[present[key]].split("=", 1)[1].strip().strip("'\"")
            if current not in PLACEHOLDERS:
                continue
            lines[present[key]] = f"{key}={generate()}"
        else:
            lines.append(f"{key}={generate()}")
        changed.append(key)
    env_path.write_text("\n".join(lines) + "\n")
    print("Generated: " + ", ".join(changed) if changed else ".env already complete")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".env")
