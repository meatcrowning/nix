"""Krea encoder controls and the fixed Turbo sampling schedule for Painter."""
import math

import comfy.model_sampling
import comfy.utils
from comfy_api.latest import ComfyExtension, io


class PainterKreaEncode(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PainterKreaEncode", category="conditioning/krea2",
            inputs=[io.Clip.Input("clip"),
                    io.String.Input("text", multiline=True),
                    io.String.Input("system_prompt", multiline=True),
                    io.Float.Input("reference_megapixels", default=0.25, min=0.01, max=4.0),
                    io.Autogrow.Input("images", template=io.Autogrow.TemplatePrefix(
                        io.Image.Input("image"), prefix="image_", min=0, max=100))],
            outputs=[io.Conditioning.Output()])

    @classmethod
    def execute(cls, clip, text, system_prompt, reference_megapixels=0.25, images=None):
        references = []
        for name in sorted(images or {}, key=lambda n: int(n.rsplit("_", 1)[-1])):
            image = images[name]
            # Split batches: the native vision encoder otherwise reads frame 0.
            for frame in image.split(1):
                h, w = frame.shape[1:3]
                scale = min(1.0, math.sqrt(reference_megapixels * 1_000_000 / (w * h)))
                width, height = max(32, round(w * scale / 32) * 32), max(32, round(h * scale / 32) * 32)
                if (width, height) != (w, h):
                    frame = comfy.utils.common_upscale(
                        frame.movedim(-1, 1), width, height, "area", "disabled").movedim(1, -1)
                references.append(frame[..., :3])
        vision = "<|vision_start|><|image_pad|><|vision_end|>" * len(references)
        # Keep an empty system turn when cleared: native Krea trims two role
        # prefixes. Assembling first also leaves literal braces in prose safe.
        prompt = (f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
                  f"<|im_start|>user\n{vision}{text}<|im_end|>\n"
                  "<|im_start|>assistant\n")
        tokens = clip.tokenize(prompt, images=references, skip_template=True, thinking=True)
        return io.NodeOutput(clip.encode_from_tokens_scheduled(tokens))


class PainterKreaSampling(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PainterKreaSampling", category="sampling/krea2",
            inputs=[io.Model.Input("model"),
                    io.Combo.Input("mode", options=["manual", "turbo_fixed"]),
                    io.Float.Input("shift", default=1.15, min=0.0, max=100.0)],
            outputs=[io.Model.Output()])

    @classmethod
    def execute(cls, model, mode, shift):
        # Same Flux/CONST schedule as Auryg's Krea2ModelSampling turbo_fixed.
        # https://github.com/Auryg/Krea-2-Two-Stage-Sampler
        class Sampling(comfy.model_sampling.ModelSamplingFlux, comfy.model_sampling.CONST):
            pass
        sampling = Sampling(model.model.model_config)
        sampling.set_parameters(shift=1.15 if mode == "turbo_fixed" else shift)
        patched = model.clone()
        patched.add_object_patch("model_sampling", sampling)
        return io.NodeOutput(patched)


class PainterKreaExtension(ComfyExtension):
    async def get_node_list(self):
        return [PainterKreaEncode, PainterKreaSampling]


async def comfy_entrypoint():
    return PainterKreaExtension()
