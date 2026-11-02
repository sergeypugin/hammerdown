import hashlib

import pytest

from hammerdown.core.updater import _verify_download


PAYLOAD = b"update payload"
VALID_SHA256 = hashlib.sha256(PAYLOAD).hexdigest()


def test_verify_download_accepts_valid_expected_checksum() -> None:
    _verify_download(PAYLOAD, {"size": len(PAYLOAD)}, VALID_SHA256)


def test_verify_download_accepts_valid_asset_digest() -> None:
    _verify_download(PAYLOAD, {"digest": f"sha256:{VALID_SHA256}"})


def test_verify_download_accepts_uppercase_checksum_and_digest() -> None:
    _verify_download(PAYLOAD, {}, VALID_SHA256.upper())
    _verify_download(PAYLOAD, {"digest": f"sha256:{VALID_SHA256.upper()}"})


@pytest.mark.parametrize(
    ("asset", "expected_sha256"),
    [
        ({"size": len(PAYLOAD)}, None),
        ({"digest": "sha256:"}, None),
        ({"digest": f"sha256:{VALID_SHA256[:-1]}"}, None),
        ({"digest": f"sha256:{VALID_SHA256[:-1]}z"}, None),
        ({"digest": VALID_SHA256}, None),
        ({}, "not-a-sha256"),
        ({}, VALID_SHA256[:-1]),
        ({}, f"{VALID_SHA256[:-1]}z"),
    ],
)
def test_verify_download_rejects_missing_or_malformed_checksum(
    asset: dict[str, object], expected_sha256: str | None
) -> None:
    with pytest.raises(RuntimeError, match="valid SHA-256"):
        _verify_download(PAYLOAD, asset, expected_sha256)


def test_verify_download_rejects_mismatched_expected_checksum() -> None:
    with pytest.raises(RuntimeError, match="checksum verification"):
        _verify_download(PAYLOAD, {}, "0" * 64)


def test_verify_download_rejects_mismatched_asset_digest() -> None:
    with pytest.raises(RuntimeError, match="checksum verification"):
        _verify_download(PAYLOAD, {"digest": f"sha256:{'0' * 64}"})


def test_verify_download_does_not_fall_back_to_size_only_validation() -> None:
    with pytest.raises(RuntimeError, match="valid SHA-256"):
        _verify_download(PAYLOAD, {"size": len(PAYLOAD), "digest": "sha512:" + "0" * 128})
