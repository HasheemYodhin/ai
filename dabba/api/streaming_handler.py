"""
Server-Sent Events (SSE) streaming handler for chat completions.

Provides async streaming of generated tokens as SSE events in the
OpenAI-compatible format.
"""

import asyncio
from typing import AsyncGenerator, Dict, List, Optional, Callable

from dabba.api.openai_compat import ChatCompletionChunk


class StreamingHandler:
    """
    Handles streaming of generated tokens via Server-Sent Events (SSE).

    Converts token-by-token generation into OpenAI-compatible SSE chunks
    that can be consumed by any OpenAI client library.

    Args:
        model_name: Name of the model being used.
        chunk_size: Number of tokens per SSE chunk.
    """

    def __init__(
        self,
        model_name: str = "dabba",
        chunk_size: int = 1,
    ):
        self.model_name = model_name
        self.chunk_size = chunk_size
        self._token_buffer: List[str] = []

    async def stream_tokens(
        self,
        token_generator: AsyncGenerator[str, None],
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens as SSE events.

        Args:
            token_generator: Async generator yielding tokens.

        Yields:
            SSE-formatted strings for each chunk.
        """
        index = 0
        try:
            async for token in token_generator:
                chunk = ChatCompletionChunk(
                    model=self.model_name,
                    choices=[
                        {
                            "index": 0,
                            "delta": {"role": "assistant", "content": token},
                            "finish_reason": None,
                        }
                    ],
                )
                yield chunk.to_sse()
                index += 1

            final_chunk = ChatCompletionChunk(
                model=self.model_name,
                choices=[
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "stop",
                    }
                ],
            )
            yield final_chunk.to_sse()
            yield ChatCompletionChunk.done()

        except Exception:
            error_chunk = ChatCompletionChunk(
                model=self.model_name,
                choices=[
                    {
                        "index": 0,
                        "delta": {},
                        "finish_reason": "error",
                    }
                ],
            )
            yield error_chunk.to_sse()
            yield ChatCompletionChunk.done()

    async def stream_from_generator(
        self,
        generator: Callable,
        *args,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """
        Stream tokens from a synchronous or async generator.

        Args:
            generator: A callable that returns an iterable of tokens.
            *args, **kwargs: Arguments for the generator.

        Yields:
            SSE-formatted strings.
        """
        result = generator(*args, **kwargs)

        if hasattr(result, "__aiter__"):
            async_gen = result
        else:

            async def to_async():
                for token in result:
                    yield token
                    await asyncio.sleep(0)

            async_gen = to_async()

        async for token in async_gen:
            if isinstance(token, int):
                token = str(token)
            yield token

    def create_chunk(
        self,
        token: str,
        index: int = 0,
        finish_reason: Optional[str] = None,
        usage: Optional[Dict[str, int]] = None,
        reasoning: Optional[str] = None,
    ) -> str:
        """
        Create a single SSE chunk for a token.

        Args:
            token: The generated token text.
            index: Choice index.
            finish_reason: Reason for finishing (None if continuing).
            usage: Real or estimated token counts to attach to this chunk —
                the frontend reads this off the final chunk (paired with
                finish_reason) to show accurate usage instead of guessing.

        Returns:
            SSE-formatted string.
        """
        chunk = ChatCompletionChunk(
            model=self.model_name,
            choices=[
                {
                    "index": index,
                    "delta": (
                        {"reasoning_content": reasoning}
                        if reasoning is not None
                        else {"content": token}
                    ),
                    "finish_reason": finish_reason,
                }
            ],
            usage=usage,
        )
        return chunk.to_sse()
