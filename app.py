import base64
import bz2
import hashlib
from pathlib import Path

SOURCE_SHA256 = "46dfa6242f468a2ce9282373cbb3baea0fe636dfdaf92ffedf9774bbba1245e8"
PAYLOAD_PARTS = ['app_payload_00.b64', 'app_payload_01.b64', 'app_payload_02.b64', 'app_payload_03.b64', 'app_payload_04.b64', 'app_payload_05.b64', 'app_payload_06.b64', 'app_payload_07.b64', 'app_payload_08.b64', 'app_payload_09.b64', 'app_payload_10.b64', 'app_payload_11.b64', 'app_payload_12.b64']

base_dir = Path(__file__).resolve().parent
payload = "".join(
    "".join((base_dir / name).read_text(encoding="ascii").split())
    for name in PAYLOAD_PARTS
)

source_bytes = bz2.decompress(base64.b64decode(payload, validate=True))
if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA256:
    raise RuntimeError("Published app payload checksum mismatch")

source = source_bytes.decode("utf-8-sig")
compiled = compile(source, "published_local_app.py", "exec")
exec(compiled)
