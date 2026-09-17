from pwdlib import PasswordHash


password_hash = PasswordHash.recommended()
dummy_hash = password_hash.hash("not-a-real-user-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, stored_hash: str | None) -> bool:
    return password_hash.verify(password, stored_hash or dummy_hash)
