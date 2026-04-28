from pathlib import Path

PARTS = [
    "app_source_part1.py",
    "app_source_part2.py",
    "app_source_part3.py",
    "app_source_part4.py",
]

source = "\n".join(
    Path(__file__).with_name(part).read_text(encoding="utf-8")
    for part in PARTS
)

exec(compile(source, "published_local_app.py", "exec"))
