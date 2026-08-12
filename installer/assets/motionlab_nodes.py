"""MotionLab helper nodes.

MotionLabRefEncode: reference-image conditioning tuned for style fidelity.
Same mechanism as TextEncodeQwenImageEditPlus (references become Qwen3-VL
vision tokens) but with a higher-resolution VL pass and a system template that
tells the model to reproduce the references' art style, not just their content.
"""

import math

import comfy.utils

STYLE_TEMPLATE = (
    "<|im_start|>system\n"
    "You are given reference image(s). Study their exact visual style: medium, "
    "linework, shading, color palette, texture, lighting and composition "
    "language. Generate a new image that follows the user's instruction while "
    "reproducing the reference style as faithfully as possible. Keep depicted "
    "characters visually consistent with the references.<|im_end|>\n"
    "<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n"
)


class MotionLabRefEncode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "clip": ("CLIP",),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "vl_size": ("INT", {"default": 512, "min": 256, "max": 1024, "step": 64}),
            },
            "optional": {
                "image1": ("IMAGE",),
                "image2": ("IMAGE",),
                "image3": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("CONDITIONING",)
    FUNCTION = "encode"
    CATEGORY = "motionlab"

    def encode(self, clip, prompt, vl_size=512, image1=None, image2=None, image3=None):
        images = [i for i in (image1, image2, image3) if i is not None]
        images_vl = []
        image_prompt = ""
        for i, image in enumerate(images):
            samples = image.movedim(-1, 1)
            total = int(vl_size * vl_size)
            scale_by = math.sqrt(total / (samples.shape[3] * samples.shape[2]))
            width = round(samples.shape[3] * scale_by)
            height = round(samples.shape[2] * scale_by)
            s = comfy.utils.common_upscale(samples, width, height, "area", "disabled")
            images_vl.append(s.movedim(1, -1))
            image_prompt += "Picture {}: <|vision_start|><|image_pad|><|vision_end|>".format(i + 1)

        tokens = clip.tokenize(image_prompt + prompt, images=images_vl, llama_template=STYLE_TEMPLATE)
        return (clip.encode_from_tokens_scheduled(tokens),)


NODE_CLASS_MAPPINGS = {"MotionLabRefEncode": MotionLabRefEncode}
NODE_DISPLAY_NAME_MAPPINGS = {"MotionLabRefEncode": "MotionLab Reference Encode"}
