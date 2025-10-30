import secrets
import base64

def generate_urlsafe_nonce(num_bytes: int = 16) -> str:
    """
    Generates a cryptographically secure, URL-safe nonce.

    This function uses the `secrets` module for generating secure random bytes
    and then encodes them using URL-safe Base64 encoding. The resulting string
    is suitable for use in URLs, HTTP headers, or other contexts where a
    unique, unguessable token is required.

    Args:
        num_bytes: The number of random bytes to generate for the nonce.
                   Defaults to 16 bytes (128 bits) for a good balance of
                   security and length.

    Returns:
        A URL-safe, Base64-encoded string representing the nonce.

    Raises:
        ValueError: If num_bytes is not a positive integer.
    """
    if not isinstance(num_bytes, int) or num_bytes <= 0:
        raise ValueError("num_bytes must be a positive integer.")

    token_bytes = secrets.token_bytes(num_bytes)
    # Encode bytes to a URL-safe string and strip any padding
    nonce = base64.urlsafe_b64encode(token_bytes).rstrip(b'=').decode('ascii')

    return nonce
