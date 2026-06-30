from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import Settings
from app.core.scheduler import PriorityGate


@dataclass(slots=True)
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int


class InferenceEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.model: Any = None
        self.processor: Any = None
        self._gate = PriorityGate()
        self.load_error: str | None = None

    @property
    def ready(self) -> bool:
        return self.model is not None and self.processor is not None

    @property
    def queue_depth(self) -> int:
        return self._gate.queue_depth

    async def load(self) -> None:
        try:
            await asyncio.to_thread(self._load_sync)
        except Exception as exc:
            self.load_error = str(exc)
            raise

    def _load_sync(self) -> None:
        model_path = Path(self.settings.model_path)
        if not model_path.is_dir():
            raise RuntimeError(f"model directory does not exist: {model_path}")
        if not (model_path / "config.json").is_file():
            raise RuntimeError(f"model config is missing: {model_path / 'config.json'}")

        import torch
        from transformers import AutoProcessor, BitsAndBytesConfig, Qwen3VLForConditionalGeneration

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required but no NVIDIA GPU is available")

        if self.settings.quantization == "8bit":
            quantization_config = BitsAndBytesConfig(load_in_8bit=True)
        else:
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )

        processor = AutoProcessor.from_pretrained(
            str(model_path),
            local_files_only=True,
        )
        model = Qwen3VLForConditionalGeneration.from_pretrained(
            str(model_path),
            local_files_only=True,
            device_map={"": 0},
            quantization_config=quantization_config,
            dtype=torch.bfloat16,
            attn_implementation=self.settings.attention_implementation,
            low_cpu_mem_usage=True,
        )
        model.eval()
        self.processor = processor
        self.model = model

    def _prepare_inputs(self, messages: list[dict[str, Any]]) -> Any:
        inputs = self.processor.apply_chat_template(
            messages,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=True,
            return_tensors="pt",
        )
        return inputs.to(self.model.device)

    @staticmethod
    def _generation_kwargs(max_tokens: int, temperature: float, top_p: float) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "max_new_tokens": max_tokens,
            "use_cache": True,
            "do_sample": temperature > 0,
        }
        if temperature > 0:
            kwargs.update(temperature=temperature, top_p=top_p)
        return kwargs

    async def generate(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        priority: str = "normal",
    ) -> GenerationResult:
        async with self._gate.slot(priority):
            return await asyncio.to_thread(
                self._generate_sync,
                messages,
                max_tokens,
                temperature,
                top_p,
            )

    def _generate_sync(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> GenerationResult:
        import torch

        inputs = self._prepare_inputs(messages)
        prompt_tokens = int(inputs["input_ids"].shape[-1])
        with torch.inference_mode():
            output = self.model.generate(
                **inputs,
                **self._generation_kwargs(max_tokens, temperature, top_p),
            )
        generated = output[:, prompt_tokens:]
        text = self.processor.batch_decode(
            generated,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0].strip()
        return GenerationResult(text, prompt_tokens, int(generated.shape[-1]))

    async def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
        priority: str = "normal",
    ) -> AsyncIterator[str]:
        from transformers import StoppingCriteria, StoppingCriteriaList, TextIteratorStreamer

        async with self._gate.slot(priority):
            inputs = await asyncio.to_thread(self._prepare_inputs, messages)
            streamer = TextIteratorStreamer(
                self.processor.tokenizer,
                skip_prompt=True,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )
            errors: list[BaseException] = []
            stop = threading.Event()

            class Cancelled(StoppingCriteria):
                def __call__(self, *args, **kwargs) -> bool:
                    return stop.is_set()

            def run_generation() -> None:
                import torch

                try:
                    with torch.inference_mode():
                        self.model.generate(
                            **inputs,
                            streamer=streamer,
                            stopping_criteria=StoppingCriteriaList([Cancelled()]),
                            **self._generation_kwargs(max_tokens, temperature, top_p),
                        )
                except BaseException as exc:  # propagated after ending the streamer
                    errors.append(exc)
                    streamer.end()

            thread = threading.Thread(target=run_generation, daemon=True)
            thread.start()
            iterator = iter(streamer)
            try:
                while True:
                    has_value, value = await asyncio.to_thread(_next_item, iterator)
                    if not has_value:
                        break
                    if value:
                        yield value
            finally:
                stop.set()
                await asyncio.to_thread(thread.join)
            if errors:
                raise RuntimeError(f"generation failed: {errors[0]}") from errors[0]


def _next_item(iterator: Any) -> tuple[bool, str]:
    try:
        return True, next(iterator)
    except StopIteration:
        return False, ""
