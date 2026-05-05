# services/api/app/models/embedding_engine.py

import torch
from ray import serve
from sentence_transformers import SentenceTransformer


@serve.deployment(
    num_replicas=1,
    ray_actor_options={"num_gpus": 0.5} # Share GPU
)
class EmbedDeployment:
    def __init__(self):
        # Load model onto GPU
        model_name = "BAAI/bge-m3"
        self.model = SentenceTransformer(model_name, device="cuda")

        # Compile for speed (Optional, requires PyTorch 2.0+)
        self.model = torch.compile(self.model)

    async def __call__(self, request):
        body = await request.json()
        texts = body.get("text")
        body.get("task_type", "document")

        # BGE-M3 handles instructions differently, simplified here:
        if isinstance(texts, str):
            texts = [texts]

        # Encode
        embeddings = self.model.encode(
            texts,
            batch_size=32,
            normalize_embeddings=True
        )

        # Convert numpy to list
        return {"embeddings": embeddings.tolist()}

app = EmbedDeployment.bind()
