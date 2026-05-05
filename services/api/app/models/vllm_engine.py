# services/api/app/models/vllm_engine.py
import os

from ray import serve
from transformers import AutoTokenizer  # For tokenizer with chat templates
from vllm import AsyncLLMEngine, EngineArgs, SamplingParams


@serve.deployment(autoscaling_config={"min_replicas": 1, "max_replicas": 10}, ray_actor_options={"num_gpus": 1})
class VLLMDeployment:
    def __init__(self):
        # Dev: 8B model (~4.5GB VRAM AWQ, fits on g5.xlarge A10G 24GB)
        # Prod: swap to "meta-llama/Meta-Llama-3-70B-Instruct" on g5.12xlarge (4x A10G)
        model_id = os.getenv("MODEL_ID", "meta-llama/Meta-Llama-3-8B-Instruct")

        # 1. Load Tokenizer for correct chat formatting
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)

        args = EngineArgs(
            model=model_id,
            quantization=os.getenv("QUANTIZATION", "awq"),
            gpu_memory_utilization=0.85,
            max_model_len=4096  # Dev: 4K context (prod: 8192 for 70B)
        )
        self.engine = AsyncLLMEngine.from_engine_args(args)

    async def __call__(self, request):
        body = await request.json()
        messages = body.get("messages", [])

        # 2. Use Standard Template Application
        # This handles system prompts, special tokens, and roles correctly for the specific model
        prompt = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        sampling_params = SamplingParams(
            temperature=body.get("temperature", 0.7),
            max_tokens=body.get("max_tokens", 1024),
            # Stop tokens are often handled by the tokenizer config, but safe to keep
            stop_token_ids=[self.tokenizer.eos_token_id, self.tokenizer.convert_tokens_to_ids("<|eot_id|>")]
        )

        request_id = str(os.urandom(8).hex())
        results_generator = self.engine.generate(prompt, sampling_params, request_id)

        final_output = None
        async for request_output in results_generator:
            final_output = request_output

        text_output = final_output.outputs[0].text
        return {"choices": [{"message": {"content": text_output, "role": "assistant"}}]}

app = VLLMDeployment.bind()
