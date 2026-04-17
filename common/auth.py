import hashlib
import secrets


def generate_pin(digits: int = 6) -> str:
    return str(secrets.randbelow(10 ** digits)).zfill(digits)


def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()


def verify_pin(input_pin: str, stored_hash: str) -> bool:
    return hash_pin(input_pin) == stored_hash
