"""Finish painter's current sampler at its last completed denoise step.

The regular ComfyUI interrupt raises out of the graph, so Decode and SaveImage
never run.  This node instead catches a stop request at the sampler callback,
returns that callback's x0 latent, and lets the normal graph finish.
"""
import threading

from aiohttp import web

import comfy.model_management
import comfy.sample
import comfy.utils
import latent_preview
from comfy_extras import nodes_custom_sampler as custom
from server import PromptServer


class _StopHere(BaseException):
    def __init__(self, latent):
        self.latent = latent


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.requested = False

    def begin(self):
        with self.lock:
            self.active += 1

    def end(self):
        with self.lock:
            self.active = max(0, self.active - 1)
            if not self.active:
                self.requested = False

    def request(self):
        with self.lock:
            if not self.active:
                return False
            self.requested = True
            return True

    def consume(self):
        with self.lock:
            if not self.requested:
                return False
            self.requested = False
            return True


STATE = _State()


@PromptServer.instance.routes.post("/painter/stop")
async def stop_and_save(_request):
    return web.json_response({"stopping": STATE.request()})


def _callback(model, steps, x0_output):
    preview = latent_preview.prepare_callback(model, steps, x0_output)

    def wrapped(step, x0, x, total):
        preview(step, x0, x, total)
        if STATE.consume():
            raise _StopHere(x0)

    return wrapped


def _out(latent, samples, x0_output, model):
    out = latent.copy()
    out.pop("downscale_ratio_spacial", None)
    out.pop("downscale_ratio_temporal", None)
    out["samples"] = samples
    x0 = x0_output.get("x0")
    if x0 is None:
        return out, out
    if samples.is_nested and not x0.is_nested:
        shapes = [x.shape for x in samples.unbind()]
        x0 = comfy.nested_tensor.NestedTensor(comfy.utils.unpack_latents(x0, shapes))
    denoised = latent.copy()
    denoised["samples"] = model.model.process_latent_out(x0.cpu())
    return out, denoised


class PainterSamplerCustom(custom.SamplerCustom):
    RETURN_TYPES = ("LATENT", "LATENT")
    FUNCTION = "sample"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",), "add_noise": ("BOOLEAN", {"default": True}),
            "noise_seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff}),
            "cfg": ("FLOAT", {"default": 8.0, "min": 0.0, "max": 100.0}),
            "positive": ("CONDITIONING",), "negative": ("CONDITIONING",),
            "sampler": ("SAMPLER",), "sigmas": ("SIGMAS",),
            "latent_image": ("LATENT",),
        }}

    @classmethod
    def sample(cls, model, add_noise, noise_seed, cfg, positive, negative,
               sampler, sigmas, latent_image):
        latent = latent_image.copy()
        image = comfy.sample.fix_empty_latent_channels(
            model, latent["samples"], latent.get("downscale_ratio_spacial"),
            latent.get("downscale_ratio_temporal"))
        latent["samples"] = image
        noise = (custom.Noise_RandomNoise(noise_seed).generate_noise(latent)
                 if add_noise else custom.Noise_EmptyNoise().generate_noise(latent))
        x0 = {}
        STATE.begin()
        try:
            try:
                samples = comfy.sample.sample_custom(
                    model, noise, cfg, sampler, sigmas, positive, negative, image,
                    noise_mask=latent.get("noise_mask"),
                    callback=_callback(model, sigmas.shape[-1] - 1, x0),
                    disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED, seed=noise_seed)
            except _StopHere as stop:
                samples = stop.latent
                x0["x0"] = samples
            return _out(latent, samples, x0, model)
        finally:
            STATE.end()


class PainterSamplerCustomAdvanced(custom.SamplerCustomAdvanced):
    RETURN_TYPES = ("LATENT", "LATENT")
    FUNCTION = "sample"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "noise": ("NOISE",), "guider": ("GUIDER",), "sampler": ("SAMPLER",),
            "sigmas": ("SIGMAS",), "latent_image": ("LATENT",),
        }}

    @classmethod
    def sample(cls, noise, guider, sampler, sigmas, latent_image):
        latent = latent_image.copy()
        image = comfy.sample.fix_empty_latent_channels(
            guider.model_patcher, latent["samples"],
            latent.get("downscale_ratio_spacial"), latent.get("downscale_ratio_temporal"))
        latent["samples"] = image
        x0 = {}
        STATE.begin()
        try:
            try:
                samples = guider.sample(
                    noise.generate_noise(latent), image, sampler, sigmas,
                    denoise_mask=latent.get("noise_mask"),
                    callback=_callback(guider.model_patcher, sigmas.shape[-1] - 1, x0),
                    disable_pbar=not comfy.utils.PROGRESS_BAR_ENABLED, seed=noise.seed)
            except _StopHere as stop:
                samples = stop.latent
                x0["x0"] = samples
            samples = samples.to(comfy.model_management.intermediate_device())
            return _out(latent, samples, x0, guider.model_patcher)
        finally:
            STATE.end()


NODE_CLASS_MAPPINGS = {
    "PainterSamplerCustom": PainterSamplerCustom,
    "PainterSamplerCustomAdvanced": PainterSamplerCustomAdvanced,
}
