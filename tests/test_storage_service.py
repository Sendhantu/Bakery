from io import BytesIO

import pytest
from werkzeug.datastructures import FileStorage

from exceptions import ValidationError
from services import storage_service as storage_service_module
from services.storage_service import StorageService


def test_product_image_upload_saves_locally_without_cloudinary(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service_module, "BASE_DIR", tmp_path)
    service = StorageService(
        {
            "ENV": "development",
            "ALLOWED_IMAGE_EXTENSIONS": {"gif", "jpeg", "jpg", "png", "webp"},
            "LOCAL_PRODUCT_IMAGE_FOLDER": "uploads/products",
        }
    )
    upload = FileStorage(
        stream=BytesIO(b"fake png content"),
        filename="fresh cake.png",
        content_type="image/png",
    )

    image_url = service.upload_product_image(upload, filename_prefix="Classic Cake")

    assert image_url.startswith("/static/uploads/products/classic-cake-")
    assert image_url.endswith(".png")
    saved_path = tmp_path / "static" / image_url.removeprefix("/static/")
    assert saved_path.read_bytes() == b"fake png content"


def test_product_image_upload_rejects_unsupported_local_file(monkeypatch, tmp_path):
    monkeypatch.setattr(storage_service_module, "BASE_DIR", tmp_path)
    service = StorageService({"ENV": "development"})
    upload = FileStorage(stream=BytesIO(b"text"), filename="cake.txt")

    with pytest.raises(ValidationError, match="Product image must be"):
        service.upload_product_image(upload)


def test_product_image_upload_still_requires_cloud_storage_in_production():
    service = StorageService({"ENV": "production"})
    upload = FileStorage(stream=BytesIO(b"fake png content"), filename="cake.png")

    with pytest.raises(ValidationError, match="Cloudinary is not configured"):
        service.upload_product_image(upload)
