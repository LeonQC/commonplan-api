import base64
from dataclasses import dataclass
from functools import lru_cache

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import settings


def _base64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class SigningKeys:
    private_pem: bytes
    public_pem: bytes
    key_id: str

    @classmethod
    def generate(cls, key_id: str) -> "SigningKeys":
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return cls(
            private_pem=private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            public_pem=private_key.public_key().public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            ),
            key_id=key_id,
        )

    def jwk(self) -> dict[str, str]:
        public_key = serialization.load_pem_public_key(self.public_pem)
        if not isinstance(public_key, rsa.RSAPublicKey):
            raise TypeError("Only RSA public keys are supported")
        numbers = public_key.public_numbers()
        return {
            "kty": "RSA",
            "use": "sig",
            "alg": settings.signing_algorithm,
            "kid": self.key_id,
            "n": _base64url_uint(numbers.n),
            "e": _base64url_uint(numbers.e),
        }


def _load_or_create_keys() -> SigningKeys:
    private_path = settings.private_key_path
    public_path = settings.public_key_path
    if private_path.exists() and public_path.exists():
        return SigningKeys(
            private_pem=private_path.read_bytes(),
            public_pem=public_path.read_bytes(),
            key_id=settings.signing_key_id,
        )

    private_path.parent.mkdir(parents=True, exist_ok=True)
    public_path.parent.mkdir(parents=True, exist_ok=True)
    keys = SigningKeys.generate(settings.signing_key_id)
    private_path.write_bytes(keys.private_pem)
    private_path.chmod(0o600)
    public_path.write_bytes(keys.public_pem)
    public_path.chmod(0o644)
    return keys


@lru_cache
def get_signing_keys() -> SigningKeys:
    return _load_or_create_keys()
