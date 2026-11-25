"""Choosing the checkpoint the image AI renders icons with (Fooocus / A1111 / ComfyUI), without a real image AI."""
import json

import pytest

from kdecustomizer import imagegen

NAMES = ["animaPencilXL_v500.safetensors", "ponyDiffusionV6XL.safetensors", "juggernautXL_v8Rundiffusion.safetensors",
         "juggernautXL_ragnarokBy.safetensors", "realvisxlV40_v40LightningBakedvae.safetensors",
         "dreamshaperXL_v21TurboDPMSDE.safetensors", "sd_xl_refiner_1.0.safetensors", "analogMadness_v70-inpainting.safetensors"]


def test_pick_model_prefers_clean_render_models():
    assert imagegen.pick_model(NAMES) in ("juggernautXL_v8Rundiffusion.safetensors",
                                          "juggernautXL_ragnarokBy.safetensors")
    assert imagegen.pick_model(["sd_xl_base_1.0.safetensors", "someAnimeMix.safetensors"]) == "sd_xl_base_1.0.safetensors"
    # only unsuitable ones (lightning/turbo/pony/inpainting/refiner) or unknown names: no pick -> default
    assert imagegen.pick_model(["ponyDiffusionV6XL.safetensors", "x_turbo.safetensors", "mystery.safetensors"]) is None


def fooocus(model: str) -> imagegen.Fooocus:
    f = object.__new__(imagegen.Fooocus)
    f.url, f.performance, f.model = "http://x", "", model
    f.comps = {
        1: {"id": 1, "type": "dropdown", "props": {"label": imagegen.BASE_MODEL, "value": NAMES[2],
                                                   "choices": [[n, n] for n in NAMES]}},
        2: {"id": 2, "type": "textbox", "props": {"elem_id": "positive_prompt"}},
    }
    return f


@pytest.mark.parametrize("model, sent", [
    ("", NAMES[2]),                                       # default: Fooocus' own value
    ("auto", imagegen.pick_model(NAMES)),
    ("realvisxlV40_v40LightningBakedvae.safetensors", "realvisxlV40_v40LightningBakedvae.safetensors"),
    ("not-installed.safetensors", NAMES[2]),              # unknown name: its default
])
def test_fooocus_sends_the_chosen_base_model(model, sent):
    f = fooocus(model)
    assert f.models() == NAMES and f.default_model() == NAMES[2]
    assert f._value(1, "p", "n", 1) == sent
    assert f._value(2, "p", "n", 1) == "p"


def test_a1111_overrides_the_checkpoint_per_request(monkeypatch):
    a = imagegen.A1111("http://x")
    monkeypatch.setattr(imagegen, "_get", lambda url, timeout=10: json.dumps([{"title": n} for n in NAMES]).encode())
    sent = {}

    def post(url, body, timeout=600):
        sent.update(body)
        return {"images": ["aGk="]}
    monkeypatch.setattr(imagegen, "_post_json", post)
    a.model = "auto"
    a.generate("p", "n", 1)
    assert sent["override_settings"] == {"sd_model_checkpoint": imagegen.pick_model(NAMES)}
    assert sent["override_settings_restore_afterwards"] is True
    sent.clear()
    a.model = ""
    a.generate("p", "n", 1)
    assert "override_settings" not in sent


def test_comfyui_uses_the_chosen_checkpoint(monkeypatch):
    c = imagegen.ComfyUI("http://x")
    info = {"CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [NAMES]}}}}
    monkeypatch.setattr(imagegen, "_get", lambda url, timeout=10: json.dumps(info).encode())
    c.model = NAMES[3]
    assert c._checkpoint() == NAMES[3]
    c.model = ""
    assert "xl" in c._checkpoint().lower()


def test_cli_list_models(monkeypatch, tmp_path, capsys):
    from kdecustomizer import cli, spec
    spec.save(spec.Theme(name="M"), tmp_path / "m.toml")
    monkeypatch.setattr(imagegen, "detect", lambda url, perf="", model="": fooocus(model))
    assert cli.main(["icons", str(tmp_path / "m.toml"), "--list-models"]) == 0
    out = capsys.readouterr().out
    assert "8 checkpoints" in out and f"default: {NAMES[2]}" in out and NAMES[0] in out
