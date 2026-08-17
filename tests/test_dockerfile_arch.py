"""The Tailwind download must follow the build architecture.

Hardcoding an architecture builds fine on the maintainer's machine and fails only
on someone else's: an x64 binary downloads and chmods successfully on arm64, then
dies at the verification step with "Exec format error" and exit code 126, which
looks like a corrupt download rather than a mismatch.

Tailwind publishes linux-x64, linux-arm64 and -musl variants of each. The base
image is Debian, so the glibc builds are the right ones.
"""

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile"


def dockerfile() -> str:
    return DOCKERFILE.read_text()


def test_the_tailwind_url_does_not_hardcode_an_architecture():
    content = dockerfile()

    assert "tailwindcss-linux-x64" not in content, (
        "hardcoded x64 asset: this fails on arm64 hosts with exit code 126"
    )
    assert "tailwindcss-linux-arm64" not in content, "hardcoded arm64 asset"


def test_the_architecture_is_taken_from_the_build_target():
    content = dockerfile()

    assert "ARG TARGETARCH" in content, (
        "TARGETARCH must be declared in the stage, or BuildKit does not pass it "
        "through to RUN"
    )
    assert "tailwindcss-linux-${tw_arch}" in content


def test_both_architectures_docker_reports_are_mapped():
    """TARGETARCH says amd64/arm64; Tailwind names them x64/arm64."""
    content = dockerfile()

    assert re.search(r"amd64\)\s*tw_arch=x64", content)
    assert re.search(r"arm64\)\s*tw_arch=arm64", content)


def test_an_unmapped_architecture_fails_loudly():
    """Better a named error than a download of something that cannot run."""
    content = dockerfile()

    assert "No Tailwind standalone build for architecture" in content
    assert re.search(r"\*\)\s*echo .* >&2; exit 1", content)


def test_the_glibc_builds_are_used_not_musl():
    """The base image is python:3.12-slim, which is Debian.

    Checks the download URL rather than the whole file: the comment above it
    mentions musl deliberately, to explain why it is not used.
    """
    content = dockerfile()

    urls = re.findall(r"https://\S*tailwindcss\S*", content)
    assert urls, "no Tailwind download URL found"
    for url in urls:
        assert "musl" not in url, f"musl build on a glibc base image: {url}"
    assert "python:3.12-slim" in content


def test_the_binary_is_verified_after_download():
    """Without this the mismatch surfaces later, during the CSS build, where the
    cause is far less obvious."""
    assert "tailwindcss --help" in dockerfile()
