import sys

from sqlalchemy import select, update

from backend.db import SessionLocal
from backend.models import DefaultModelPreference, LearningSpace, ProviderCredential, TaskModelRoute, User

LEGACY_USER_ID = "00000000-0000-0000-0000-000000000001"


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: python -m backend.scripts.claim_legacy_data USERNAME")
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.username == sys.argv[1]))
        if not user:
            raise SystemExit(f"user not found: {sys.argv[1]}")
        for model in (LearningSpace, ProviderCredential, TaskModelRoute, DefaultModelPreference):
            result = db.execute(update(model).where(model.user_id == LEGACY_USER_ID).values(user_id=user.id))
            print(f"{model.__tablename__}: {result.rowcount}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
