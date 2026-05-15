from flask import Blueprint, jsonify

api_v2_bp = Blueprint("api_v2", __name__)


@api_v2_bp.route("/meta")
def meta():
    return jsonify(
        {
            "version": "v2",
            "status": "planned",
            "message": "V2 is reserved for future mobile and integration-focused contracts.",
        }
    )
