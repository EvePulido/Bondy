from unittest.mock import MagicMock, patch

from bondy.app_utils import vision_tools
from bondy.app_utils.vision_tools import _quota_retry_delay


def test_quota_delay_parses_retry_in_seconds():
    err = Exception("429 RESOURCE_EXHAUSTED. Please retry in 49.1s.")
    assert _quota_retry_delay(err) == 50.1


def test_quota_delay_is_capped():
    assert _quota_retry_delay(Exception("429 retry in 500s")) == 60.0


def test_quota_delay_ignores_other_errors():
    assert _quota_retry_delay(Exception("503 UNAVAILABLE")) is None


def test_generate_retries_same_model_once_on_quota_error():
    ok = MagicMock(text="done")
    client = MagicMock()
    client.models.generate_content.side_effect = [Exception("429 retry in 1s"), ok]
    with (
        patch("google.genai.Client", return_value=client),
        patch.object(vision_tools.time, "sleep") as sleep,
    ):
        assert vision_tools._generate(["x"]) == "done"
    sleep.assert_called_once()
    models = [c.kwargs["model"] for c in client.models.generate_content.call_args_list]
    assert models[0] == models[1] == vision_tools.VISION_MODEL


def test_skip_note_only_for_images_only_audit():
    from bondy.fast_api_app import _skip_note

    assert "STEP 1.5" in _skip_note(["WCAG 1.1.1"])
    assert _skip_note(["WCAG 1.1.1", "WCAG 3.1.1"]) == ""
    assert _skip_note(None) == ""


def test_daily_quota_is_not_retried():
    err = Exception(
        "429 RESOURCE_EXHAUSTED quotaId 'GenerateRequestsPerDayPerProjectPerModel-FreeTier'"
    )
    assert _quota_retry_delay(err) is None
