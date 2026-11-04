import argparse
import hashlib
import os
from pathlib import Path


LARGE_SIZE = 50 * 1024 * 1024
SMALL_SIZE = 10 * 1024
SMALL_COUNT = 100
CHUNK_SIZE = 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_atomic(path: Path, chunks) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as output:
        for chunk in chunks:
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def ensure_large(root: Path) -> Path:
    destination = root / "workloads" / "large-50mib.bin"
    if not destination.is_file() or destination.stat().st_size != LARGE_SIZE:
        block = bytes(range(256)) * (CHUNK_SIZE // 256)
        write_atomic(destination, (block for _ in range(LARGE_SIZE // CHUNK_SIZE)))
    return destination


def small_content(index: int) -> bytes:
    marker = f"redes2-object-{index:03d}\n".encode("ascii")
    repeated = marker * ((SMALL_SIZE // len(marker)) + 1)
    return repeated[:SMALL_SIZE]


def ensure_small(root: Path) -> tuple[Path, list[Path]]:
    directory = root / "workloads" / "small"
    files: list[Path] = []
    for index in range(1, SMALL_COUNT + 1):
        destination = directory / f"object-{index:03d}.bin"
        content = small_content(index)
        if (
            not destination.is_file()
            or destination.stat().st_size != SMALL_SIZE
            or sha256(destination) != hashlib.sha256(content).hexdigest()
        ):
            write_atomic(destination, (content,))
        files.append(destination)

    manifest = directory / "manifest.txt"
    lines = "".join(
        f"/workloads/small/{path.name}\n" for path in files
    ).encode("utf-8")
    if not manifest.is_file() or manifest.read_bytes() != lines:
        write_atomic(manifest, (lines,))
    return manifest, files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera e valida as cargas binarias da matriz experimental"
    )
    parser.add_argument("--output", default="servers/content")
    args = parser.parse_args()

    root = Path(args.output)
    large = ensure_large(root)
    manifest, small_files = ensure_small(root)

    if large.stat().st_size != LARGE_SIZE:
        raise RuntimeError("a Carga A nao possui exatamente 50 MiB")
    if len(small_files) != SMALL_COUNT:
        raise RuntimeError("a Carga B nao possui exatamente 100 objetos")
    if any(path.stat().st_size != SMALL_SIZE for path in small_files):
        raise RuntimeError("um objeto da Carga B nao possui exatamente 10 KiB")

    print(f"large={large} bytes={large.stat().st_size} sha256={sha256(large)}")
    print(
        f"small_manifest={manifest} files={len(small_files)} "
        f"bytes_each={SMALL_SIZE} total_bytes={SMALL_COUNT * SMALL_SIZE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
