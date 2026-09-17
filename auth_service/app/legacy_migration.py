"""Idempotently move legacy credentials into the independent auth database.

This bridge exists only while Zhitong's original users table still contains
password_hash/google_sub. It deliberately does not migrate refresh tokens, so
existing browser sessions must authenticate again after the service split.
"""

import os
import uuid

from sqlalchemy import create_engine, text

from app.config import settings


LEGACY_NAMESPACE = uuid.UUID("419cce80-f40d-46f3-95a4-78cd337580d3")


def migrate() -> int:
    legacy_url = os.environ["LEGACY_DATABASE_URL"]
    legacy_engine = create_engine(legacy_url, pool_pre_ping=True)
    auth_engine = create_engine(settings.database_url, pool_pre_ping=True)
    migrated = 0

    with legacy_engine.begin() as legacy_db, auth_engine.begin() as auth_db:
        duplicate_email = legacy_db.execute(
            text(
                """
                SELECT lower(email)
                FROM users
                GROUP BY lower(email)
                HAVING count(*) > 1
                LIMIT 1
                """
            )
        ).scalar_one_or_none()
        if duplicate_email is not None:
            raise RuntimeError(
                "Legacy users contain case-insensitive duplicate email addresses; "
                f"resolve {duplicate_email!r} before migrating identities"
            )

        users = legacy_db.execute(
            text(
                """
                SELECT id, email, name, password_hash, google_sub, avatar_url,
                       is_deleted, auth_issuer, auth_subject
                FROM users
                ORDER BY id
                """
            )
        ).mappings()

        for legacy_user in users:
            existing = auth_db.execute(
                text("SELECT id FROM identity_users WHERE lower(email) = lower(:email)"),
                {"email": legacy_user["email"]},
            ).scalar_one_or_none()
            linked_subject = (
                legacy_user["auth_subject"]
                if legacy_user["auth_issuer"] == settings.issuer
                else None
            )
            if existing is not None and linked_subject is not None and existing != linked_subject:
                raise RuntimeError(
                    "Legacy profile and Auth Service disagree about the identity subject for "
                    f"{legacy_user['email']!r}"
                )
            subject = existing or linked_subject or str(
                uuid.uuid5(LEGACY_NAMESPACE, f"legacy-user:{legacy_user['id']}")
            )

            if existing is None:
                auth_db.execute(
                    text(
                        """
                        INSERT INTO identity_users (
                            id, email, name, password_hash, avatar_url, is_active
                        ) VALUES (
                            :id, lower(:email), :name, :password_hash, :avatar_url,
                            :is_active
                        )
                        """
                    ),
                    {
                        "id": subject,
                        "email": legacy_user["email"],
                        "name": legacy_user["name"],
                        "password_hash": legacy_user["password_hash"],
                        "avatar_url": legacy_user["avatar_url"],
                        "is_active": not legacy_user["is_deleted"],
                    },
                )

            if legacy_user["google_sub"]:
                auth_db.execute(
                    text(
                        """
                        INSERT INTO external_identities (provider, subject, user_id)
                        VALUES ('google', :google_sub, :user_id)
                        ON CONFLICT (provider, subject) DO NOTHING
                        """
                    ),
                    {
                        "google_sub": legacy_user["google_sub"],
                        "user_id": subject,
                    },
                )

            legacy_db.execute(
                text(
                    """
                    UPDATE users
                    SET auth_issuer = :issuer,
                        auth_subject = :subject
                    WHERE id = :id
                      AND (auth_issuer IS NULL OR auth_subject IS NULL)
                    """
                ),
                {
                    "issuer": settings.issuer,
                    "subject": subject,
                    "id": legacy_user["id"],
                },
            )
            migrated += 1

    return migrated


if __name__ == "__main__":
    print(f"Legacy identities synchronized: {migrate()}")
