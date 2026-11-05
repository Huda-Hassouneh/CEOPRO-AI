"""Image generation: more than ten models tried best first, a model at its limit set aside so the next
image goes to the next one, the 10-second limit, the quality gate, and exact text in the picture."""
import io

import pytest
from PIL import Image, ImageDraw

from src.ai.marketing import designed_poster, image_generation as ig


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _scene(size=(1024, 1024), base=(200, 120, 40)):
    image = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(image)
    for i in range(0, 1024, 40):
        draw.ellipse((i, (i * 7) % 900, i + 160, (i * 7) % 900 + 160), fill=((i * 3) % 255, (i * 5) % 255, 90),
                     outline=(20, 20, 20), width=3)
    return image


GOOD = _png(_scene())


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("MARKETING_IMAGE_PROVIDER", "MARKETING_IMAGE_PROVIDERS", "MARKETING_IMAGE_TOTAL_SECONDS",
                 "LOCAL_IMAGE_BASE_URL", "LOCAL_IMAGE_BASE_URLS", "HUGGINGFACE_API_TOKEN", "HUGGINGFACE_API_TOKENS",
                 "CLOUDFLARE_ACCOUNTS", "CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN", "GEMINI_API_KEYS",
                 "TOGETHER_API_KEYS", "POLLINATIONS_API_KEYS", "GEMINI_IMAGE_MODEL", "TOGETHER_IMAGE_MODEL",
                 "POLLINATIONS_MODEL", "CLOUDFLARE_IMAGE_MODELS", "HUGGINGFACE_IMAGE_MODELS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MARKETING_IMAGE_KEYLESS", "false")
    cooling = set()
    monkeypatch.setattr(ig, "_cooling_down", lambda name: name in cooling)
    monkeypatch.setattr(ig, "_cool_down", lambda name, seconds: cooling.add(name))

    class _Call:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def measured(self, *_):
            pass

    monkeypatch.setattr(ig.credits, "provider_call", lambda *a, **k: _Call())
    return cooling


def _fake_providers(monkeypatch, behaviour):
    """Every provider answers with behaviour(base, model) -> bytes, or raises what it returns."""
    calls = []

    def make(base):
        def provider(prompt, credential=None, size=None, seed=None, **_):
            model = ig._pinned_model()
            calls.append((base, model, prompt))
            result = behaviour(base, model)
            if isinstance(result, Exception):
                raise result
            return ig.GeneratedImage(content=result, content_type="image/png", provider=base, model=model)
        return provider

    for base in list(ig._PROVIDERS):
        monkeypatch.setitem(ig._PROVIDERS, base, make(base))
    return calls


def _all_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEYS", "g")
    monkeypatch.setenv("TOGETHER_API_KEYS", "t")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNTS", "acc:tok")
    monkeypatch.setenv("HUGGINGFACE_API_TOKENS", "h")
    monkeypatch.setenv("POLLINATIONS_API_KEYS", "p")


# --- models -------------------------------------------------------------------------

def test_more_than_ten_hosted_models_are_available():
    hosted = [(base, model) for base, models in ig.MODEL_CATALOG.items() if base not in ("local", "aihorde")
              for model, _rank in models]
    assert len(hosted) > 10
    assert len({model for _base, model in hosted}) > 10


def test_the_best_model_is_tried_first_across_providers(monkeypatch):
    _all_keys(monkeypatch)
    calls = _fake_providers(monkeypatch, lambda base, model: GOOD)
    image = ig.generate_campaign_image("olive oil bottle on a wooden table")
    assert (image.provider, image.model) == ("gemini", "gemini-2.5-flash-image")
    assert len(calls) == 1


def test_a_model_at_its_limit_sends_the_next_image_to_the_next_model(monkeypatch, _env):
    _all_keys(monkeypatch)
    exhausted = {"gemini-2.5-flash-image"}

    def behaviour(base, model):
        if model in exhausted:
            return ig.ProviderBusy("daily limit", 3600, scope="model")
        return GOOD

    calls = _fake_providers(monkeypatch, behaviour)
    ig.generate_campaign_image("x")
    assert "gemini#1@gemini-2.5-flash-image" in _env and "gemini#1" not in _env  # only that model set aside
    calls.clear()
    second = ig.generate_campaign_image("x")
    assert all(model != "gemini-2.5-flash-image" for _b, model, _p in calls)  # skipped without a call
    assert second.model != "gemini-2.5-flash-image"


def test_an_account_out_of_allowance_skips_all_its_models(monkeypatch, _env):
    _all_keys(monkeypatch)
    calls = _fake_providers(monkeypatch, lambda base, model: ig.ProviderBusy("quota", 3600) if base == "cloudflare" else GOOD)
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "cloudflare,huggingface")
    image = ig.generate_campaign_image("x")
    assert image.provider == "huggingface"
    assert [b for b, _m, _p in calls].count("cloudflare") == 1  # one refusal; its other five models not called
    assert "cloudflare" in _env  # the account (listed by name) is set aside, not just one model


# --- time limit ---------------------------------------------------------------------

def test_one_image_never_takes_more_than_the_limit(monkeypatch):
    _all_keys(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(ig.time, "monotonic", lambda: clock[0])
    seen_timeouts = []

    def behaviour(base, model):
        seen_timeouts.append(ig._timeout())
        clock[0] += 6.0  # every model is slow and fails
        return ig.ImageGenerationError("PROVIDER_ERROR", "slow and broken")

    _fake_providers(monkeypatch, behaviour)
    with pytest.raises(ig.ImageGenerationError) as exc:
        ig.generate_campaign_image("x")
    assert ig.total_seconds() == 10.0
    assert seen_timeouts[0] <= 10.0 and seen_timeouts[1] <= 4.0  # each call is cut to the time left
    assert len(seen_timeouts) == 2  # 6 s + 6 s: the third model would start after the limit
    assert any(a["reason"] == "out_of_time" for a in exc.value.attempts)
    assert "within 10 s" in exc.value.message


def test_ai_horde_is_not_tried_when_it_cannot_answer_in_time(monkeypatch):
    monkeypatch.setenv("HUGGINGFACE_API_TOKENS", "h")
    monkeypatch.setenv("MARKETING_IMAGE_KEYLESS", "true")
    calls = _fake_providers(monkeypatch, lambda base, model: ig.ImageGenerationError("PROVIDER_ERROR", "down"))
    with pytest.raises(ig.ImageGenerationError):
        ig.generate_campaign_image("x")
    assert "aihorde" not in [b for b, _m, _p in calls]


def test_a_self_hosted_only_deployment_keeps_its_own_time_limit(monkeypatch):
    monkeypatch.setenv("LOCAL_IMAGE_BASE_URL", "http://gpu-box:7860")
    monkeypatch.setenv("MARKETING_IMAGE_PROVIDERS", "local")
    assert ig.total_seconds() == ig._LOCAL_IMAGE_TIMEOUT_SECONDS
    monkeypatch.setenv("MARKETING_IMAGE_TOTAL_SECONDS", "10")
    assert ig.total_seconds() == 10.0


# --- quality gate -------------------------------------------------------------------

@pytest.mark.parametrize("bad, why", [
    (Image.new("RGB", (1024, 1024), (0, 0, 0)), "black"),            # a safety filter's black frame
    (Image.new("RGB", (1024, 1024), (255, 255, 255)), "white"),
    (Image.new("RGB", (1024, 1024), (120, 160, 200)), "contrast"),   # one flat colour
])
def test_unacceptable_images_are_rejected(bad, why):
    problems = ig.quality_problems(_png(bad))
    assert problems and any(why in p for p in problems)


def test_a_blurred_smear_is_rejected():
    smear = Image.linear_gradient("L").resize((1024, 1024)).convert("RGB")
    assert ig.quality_problems(_png(smear))


@pytest.mark.parametrize("style", sorted(designed_poster.STYLES))
def test_real_scenes_pass_including_minimal_and_dark_ones(style):
    scene = designed_poster.procedural_scene(style, (1024, 1024), seed=3).convert("RGB")
    draw = ImageDraw.Draw(scene)  # a product on the backdrop
    draw.rounded_rectangle((380, 300, 640, 800), radius=40, fill=(90, 120, 40), outline=(30, 30, 30), width=4)
    assert ig.quality_problems(_png(scene)) == []


def test_a_rejected_image_goes_to_the_next_model(monkeypatch):
    _all_keys(monkeypatch)
    black = _png(Image.new("RGB", (1024, 1024), (0, 0, 0)))
    _fake_providers(monkeypatch, lambda base, model: black if base == "gemini" else GOOD)
    image = ig.generate_campaign_image("x")
    assert image.attempts[0] == {"provider": "gemini#1@gemini-2.5-flash-image", "reason": "rejected",
                                 "problems": image.attempts[0]["problems"]}
    # The next best: a FLUX.1 [schnell] model (equal ranks rotate between accounts to spread the load).
    assert image.provider != "gemini" and "flux" in image.model.lower() and "schnell" in image.model.lower()


# --- words in the picture -----------------------------------------------------------

def test_text_is_written_exactly_and_the_model_is_told_to_draw_none(monkeypatch):
    _all_keys(monkeypatch)
    calls = _fake_providers(monkeypatch, lambda base, model: GOOD)
    image = ig.generate_campaign_image("olive oil", text="Eid offer: 20% off")
    assert image.text == "Eid offer: 20% off" and image.content_type == "image/png"
    assert image.content != GOOD
    assert "no text, letters" in calls[0][2]  # lettering is never left to the model
    assert ig.quality_problems(image.content) == []


def test_arabic_text_is_drawn_on_any_format():
    for size in ((1024, 1024), (768, 1344), (1344, 704)):
        out = designed_poster.overlay_headline(_png(_scene(size)), "عرض العيد: خصم ٢٠٪ على زيت الزيتون")
        picture = Image.open(io.BytesIO(out))
        assert picture.size == size


def test_without_text_the_image_is_untouched(monkeypatch):
    _all_keys(monkeypatch)
    calls = _fake_providers(monkeypatch, lambda base, model: GOOD)
    image = ig.generate_campaign_image("olive oil")
    assert image.text is None and "no text, letters" not in calls[0][2]
