import httpx

from backend.agent.settings import EmbeddingSettings

MAX_EMBEDDING_BATCH_SIZE = 25


class Embedding:
    def __init__(
        self,
        model_name: str = "text-embedding-v1",
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/api/v1/services/embeddings/text-embedding/text-embedding",
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url
        self._embedding_set = EmbeddingSettings()

        self.set_embedding()  # 默认，设置embedding模型

    def set_embedding(self):
        self.model_name = self._embedding_set.model_name
        self.api_key = self._embedding_set.api_key

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), MAX_EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + MAX_EMBEDDING_BATCH_SIZE]
            embeddings.extend(self._embed(batch))
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], text_type="query")[0]

    def _embed(self, texts: list[str], *, text_type: str | None = None) -> list[list[float]]:
        payload = {
            "model": self.model_name,
            "input": {
                "texts": texts,
            },
        }
        if text_type is not None:
            payload["parameters"] = {"text_type": text_type}

        response = httpx.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(f"Embedding API failed: {exc.response.status_code} {exc.response.text}") from exc

        data = response.json()
        embeddings = data["output"]["embeddings"]

        embeddings = sorted(embeddings, key=lambda item: item["text_index"])
        return [item["embedding"] for item in embeddings]
