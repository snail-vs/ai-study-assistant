import hashlib
import secrets
import sys

from backend.db import SessionLocal
from backend.models import InviteCode


def main() -> None:
    raw_code = sys.argv[1] if len(sys.argv) > 1 else secrets.token_urlsafe(12)
    db = SessionLocal()
    try:
        db.add(InviteCode(code_hash=hashlib.sha256(raw_code.encode()).hexdigest()))
        db.commit()
    finally:
        db.close()
    print(raw_code)


if __name__ == "__main__":
    main()
