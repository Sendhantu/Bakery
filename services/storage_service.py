import os

try:
    import cloudinary
    import cloudinary.api
    import cloudinary.uploader
except ImportError:  # pragma: no cover
    cloudinary = None

from exceptions import ValidationError


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
            raise ValidationError(
                "Cloudinary is not configured. Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, and CLOUDINARY_API_SECRET."
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
