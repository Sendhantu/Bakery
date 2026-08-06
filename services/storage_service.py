import os
from pathlib import Path

from werkzeug.utils import secure_filename

try:
    import cloudinary
    import cloudinary.api
    import cloudinary.uploader
except ImportError:  # pragma: no cover
    cloudinary = None

from exceptions import ValidationError


BASE_DIR = Path(__file__).resolve().parents[1]
LOCAL_PRODUCT_UPLOAD_FOLDER = "uploads/products"


class StorageService:
    def __init__(self, config):
        self.config = config
        self._configured = False

    def is_configured(self):
        return bool(
            cloudinary
            and self.config.get("CLOUDINARY_CLOUD_NAME")
            and self.config.get("CLOUDINARY_API_KEY")
            and self.config.get("CLOUDINARY_API_SECRET")
        )

    def configure(self):
        if self._configured or not self.is_configured():
            return
        cloudinary.config(
            cloud_name=self.config["CLOUDINARY_CLOUD_NAME"],
            api_key=self.config["CLOUDINARY_API_KEY"],
            api_secret=self.config["CLOUDINARY_API_SECRET"],
            secure=True,
        )
        self._configured = True

    def upload_product_image(self, file_storage, *, filename_prefix="product"):
        if not self.is_configured():
            if self._requires_cloud_storage():
                raise ValidationError(
                    "Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."
                )
            return self._upload_product_image_locally(
                file_storage,
                filename_prefix=filename_prefix,
            )

        self.configure()
        public_id = f"{filename_prefix}-{os.urandom(4).hex()}"
        result = cloudinary.uploader.upload(
            file_storage,
            folder=self.config.get("PRODUCT_IMAGE_FOLDER", "sweetcrumbs/products"),
            public_id=public_id,
            overwrite=True,
            invalidate=True,
            resource_type="image",
            format="webp",
            transformation=[
                {"quality": "auto", "fetch_format": "auto"},
            ],
        )
        return result["secure_url"]

    def _requires_cloud_storage(self):
        env_name = str(self.config.get("ENV") or "").strip().lower()
        return env_name == "production" or bool(self.config.get("STORAGE_REQUIRED"))

    def _allowed_image_extensions(self):
        configured_extensions = self.config.get("ALLOWED_IMAGE_EXTENSIONS") or {
            "gif",
            "jpeg",
            "jpg",
            "png",
            "webp",
        }
        return {
            str(extension).lower().lstrip(".")
            for extension in configured_extensions
            if extension
        }

    def _validate_image_filename(self, filename):
        safe_name = secure_filename(filename or "")
        if "." not in safe_name:
            raise ValidationError(
                "Product image must be a JPG, PNG, WebP, or GIF file."
            )

        extension = safe_name.rsplit(".", 1)[1].lower()
        if extension not in self._allowed_image_extensions():
            raise ValidationError(
                "Product image must be a JPG, PNG, WebP, or GIF file."
            )
        return extension

    def _local_upload_parts(self):
        folder = str(
            self.config.get("LOCAL_PRODUCT_IMAGE_FOLDER")
            or LOCAL_PRODUCT_UPLOAD_FOLDER
        ).strip()
        parts = [
            secure_filename(part)
            for part in folder.strip("/").split("/")
            if part and part not in {".", ".."}
        ]
        return parts or ["uploads", "products"]

    def _local_filename_prefix(self, filename_prefix):
        safe_prefix = secure_filename(filename_prefix or "product").strip("-_")
        return safe_prefix.lower().replace("_", "-") or "product"

    def _upload_product_image_locally(self, file_storage, *, filename_prefix):
        extension = self._validate_image_filename(getattr(file_storage, "filename", ""))
        upload_parts = self._local_upload_parts()
        target_dir = BASE_DIR / "static" / Path(*upload_parts)
        target_dir.mkdir(parents=True, exist_ok=True)

        file_name = (
            f"{self._local_filename_prefix(filename_prefix)}-"
            f"{os.urandom(4).hex()}.{extension}"
        )
        target_path = target_dir / file_name
        file_storage.save(str(target_path))
        return f"/static/{'/'.join(upload_parts)}/{file_name}"

    def upload_bytes(self, payload, *, public_id, resource_type="raw", format_ext="pdf"):
        if not self.is_configured():
            raise ValidationError("Cloudinary is not configured.")
        self.configure()
        result = cloudinary.uploader.upload(
            payload,
            public_id=public_id,
            resource_type=resource_type,
            format=format_ext,
            overwrite=True,
            invalidate=True,
        )
        return {"url": result.get("secure_url"), "public_id": result.get("public_id")}

    def verify_connection(self):
        if not self.is_configured():
            return {"status": "not_configured"}
        self.configure()
        try:
            cloudinary.api.ping()
            return {"status": "ok"}
        except Exception as exc:  # pragma: no cover
            return {"status": "error", "error": str(exc)}
