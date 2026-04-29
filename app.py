import base64
import bz2
import hashlib
from pathlib import Path

SOURCE_SHA256 = "85c61351af6eeb88996a9d2b68c5f7e1e3c0ad93809d7e27373ca53abf9c9330"
PAYLOAD_PREFIX_LENGTH = 39989

base_dir = Path(__file__).resolve().parent
payload_prefix = "".join((base_dir / "app_payload.b64").read_text(encoding="ascii").split())[:PAYLOAD_PREFIX_LENGTH]
payload_tail = "".join((base_dir / "app_payload_tail.b64").read_text(encoding="ascii").split())
payload = payload_prefix + payload_tail

source_bytes = bz2.decompress(base64.b64decode(payload, validate=True))
if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA256:
    raise RuntimeError("Published app payload checksum mismatch")

source = source_bytes.decode("utf-8-sig")
compiled = compile(source, "published_local_app.py", "exec")
exec(compiled)
