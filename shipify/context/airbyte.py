"""
Airbyte — shared context layer for all agents.

Triggers a sync of the Slack connector → vector store (Pinecone).
All three agents query the vector store for RAG-grounded context
before acting (e.g. "what did the team decide about auth last sprint?").
"""
import httpx
from shipify.config import cfg


class AirbyteContext:
    """Trigger Airbyte syncs and query the resulting vector store."""

    _AIRBYTE_API = "https://api.airbyte.com/v1"

    def trigger_sync(self) -> str:
        """Kick off the Slack → vector store pipeline. Returns job ID."""
        resp = httpx.post(
            f"{self._AIRBYTE_API}/jobs",
            json={"connectionId": cfg.airbyte_connection_id, "jobType": "sync"},
            headers={
                "Authorization": f"Bearer {cfg.airbyte_api_key}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        job_id = resp.json()["jobId"]
        print(f"[Airbyte] Sync triggered → job {job_id}")
        return job_id

    def sync_status(self, job_id: str) -> str:
        resp = httpx.get(
            f"{self._AIRBYTE_API}/jobs/{job_id}",
            headers={"Authorization": f"Bearer {cfg.airbyte_api_key}"},
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("status", "unknown")

    def query_context(self, query: str, top_k: int = 5) -> list[dict]:
        """
        Query Pinecone for relevant Slack/decision context.
        Returns ranked chunks with text + metadata.
        """
        from pinecone import Pinecone  # type: ignore
        import openai  # type: ignore

        pc = Pinecone(api_key=cfg.pinecone_api_key)
        index = pc.Index(cfg.pinecone_index)

        # Embed the query with the same model used during ingestion
        client = openai.OpenAI()
        embedding = (
            client.embeddings.create(input=query, model="text-embedding-3-small")
            .data[0]
            .embedding
        )

        results = index.query(vector=embedding, top_k=top_k, include_metadata=True)
        chunks = [
            {"text": m["metadata"].get("text", ""), "source": m["metadata"].get("source", "")}
            for m in results["matches"]
        ]
        print(f"[Airbyte/Pinecone] Retrieved {len(chunks)} context chunks for: '{query[:60]}'")
        return chunks


airbyte_context = AirbyteContext()
