from unittest.mock import patch

from app import oauth


class Response403:
    status_code = 403
    text = "forbidden"

    @staticmethod
    def json():
        return {"errors": [{"type": "forbidden", "value": "vacancy_not_available"}]}


def test_apply_403_does_not_invalidate_valid_oauth_token():
    acc = {"resume_hash": "resume", "cookies": {"hhtoken": "cookie"}}
    with patch.object(oauth, "_obtain_oauth_token", return_value="valid-token"), \
         patch.object(oauth.HH, "post", return_value=Response403()), \
         patch.object(oauth, "invalidate_oauth_token") as invalidate:
        result, info = oauth._oauth_apply(acc, "vacancy")
    assert result == "error"
    assert info["http_status"] == 403
    invalidate.assert_not_called()


class Response200:
    status_code = 200
    text = "{}"

    @staticmethod
    def json():
        return {}


def test_oauth_apply_uses_configured_fallback_letter():
    acc = {"resume_hash": "resume", "cookies": {"hhtoken": "cookie"}}
    captured = {}
    def fake_post(*args, **kwargs):
        captured["data"] = kwargs.get("data") or {}
        return Response200()

    with patch.object(oauth.CONFIG, "letter_templates", [{"name": "x", "text": "fallback letter"}]), \
         patch.object(oauth, "_obtain_oauth_token", return_value="valid-token"), \
         patch.object(oauth.HH, "post", side_effect=fake_post):
        result, _ = oauth._oauth_apply(acc, "vacancy", "")
    assert result == "sent"
    assert captured["data"]["message"] == "fallback letter"
