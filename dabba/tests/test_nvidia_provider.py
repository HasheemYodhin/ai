from dabba.providers.nvidia_provider import NvidiaProvider, _CONTINUE_PROMPT


def test_glm_disables_thinking_by_default():
    params = NvidiaProvider()._build_params(
        [{"role": "user", "content": "Hello"}],
        "z-ai/glm-5.2",
        max_tokens=256,
    )

    assert params["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}


def test_glm_enables_thinking_when_requested():
    params = NvidiaProvider()._build_params(
        [{"role": "user", "content": "Solve this carefully"}],
        "z-ai/glm-5.2",
        thinking=True,
    )

    assert params["extra_body"]["chat_template_kwargs"]["enable_thinking"] is True


def test_other_nvidia_models_do_not_receive_glm_chat_template_options():
    params = NvidiaProvider()._build_params(
        [{"role": "user", "content": "Hello"}],
        "meta/llama-3.1-8b-instruct",
    )

    assert "extra_body" not in params


def test_degraded_model_raises_user_friendly_error():
    import pytest
    from unittest.mock import MagicMock, patch

    provider = NvidiaProvider()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = Exception(
        "Error: DEGRADED function cannot be invoked"
    )

    with patch.object(provider, "_client", return_value=mock_client):
        with pytest.raises(RuntimeError) as exc_info:
            provider.chat(
                [{"role": "user", "content": "Hello"}],
                "thinkingmachines/inkling",
                api_key="dummy_key",
            )
        assert "temporarily degraded/unavailable" in str(exc_info.value)


def test_gemma_converts_system_role():
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello"},
    ]
    params = NvidiaProvider()._build_params(
        messages,
        "google/gemma-2-2b-it",
    )
    # Check that system role is removed
    for msg in params["messages"]:
        assert msg["role"] != "system"
    # Check that first user message has the system prompt prepended
    user_msg = params["messages"][0]
    assert user_msg["role"] == "user"
    assert "You are a helpful assistant." in user_msg["content"]
    assert "Hello" in user_msg["content"]


def test_deepseek_v4_uses_slow_model_timeout():
    from dabba.providers.nvidia_provider import SLOW_REASONING_TIMEOUT_SECONDS

    provider = NvidiaProvider()

    assert (
        provider._timeout_for_model("deepseek-ai/deepseek-v4-flash")
        == SLOW_REASONING_TIMEOUT_SECONDS
    )


def test_stream_chat_retries_nvidia_worker_capacity_errors():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    provider = NvidiaProvider()
    mock_client = MagicMock()
    successful_stream = iter(
        [
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Hello"),
                        finish_reason="stop",
                    )
                ],
            )
        ]
    )
    mock_client.chat.completions.create.side_effect = [
        Exception(
            "503 ResourceExhausted: Worker local total request limit reached (48/48)"
        ),
        successful_stream,
    ]

    with (
        patch.object(provider, "_client", return_value=mock_client),
        patch("time.sleep") as sleep,
    ):
        chunks = list(
            provider.stream_chat(
                [{"role": "user", "content": "Hello"}],
                "deepseek-ai/deepseek-v4-flash",
                api_key="dummy_key",
            )
        )

    assert chunks == ["Hello"]
    assert mock_client.chat.completions.create.call_count == 2
    sleep.assert_called_once_with(3.0)


def test_deepseek_v4_falls_back_after_capacity_retries():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    provider = NvidiaProvider()
    mock_client = MagicMock()
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Fallback answer", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    capacity_error = Exception(
        "503 ResourceExhausted: Worker local total request limit reached (48/48)"
    )
    mock_client.chat.completions.create.side_effect = [
        capacity_error,
        capacity_error,
        capacity_error,
        response,
    ]

    with (
        patch.object(provider, "_client", return_value=mock_client),
        patch("time.sleep"),
    ):
        result = provider.chat(
            [{"role": "user", "content": "Write Python code"}],
            "deepseek-ai/deepseek-v4-flash",
            api_key="dummy_key",
        )

    assert "used `qwen/qwen2.5-coder-32b-instruct`" in result
    assert result.endswith("Fallback answer")
    assert (
        mock_client.chat.completions.create.call_args.kwargs["model"]
        == "qwen/qwen2.5-coder-32b-instruct"
    )


def test_stream_chat_recovers_when_lazy_stream_fails_before_first_token():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    def capacity_stream():
        raise Exception(
            "ResourceExhausted: Worker local total request limit reached (367/48)"
        )
        yield  # pragma: no cover

    successful_stream = iter(
        [
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="Fallback answer"),
                        finish_reason="stop",
                    )
                ],
            )
        ]
    )
    provider = NvidiaProvider()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        capacity_stream(),
        capacity_stream(),
        capacity_stream(),
        successful_stream,
    ]

    with (
        patch.object(provider, "_client", return_value=mock_client),
        patch("time.sleep"),
    ):
        chunks = list(
            provider.stream_chat(
                [{"role": "user", "content": "Hello"}],
                "deepseek-ai/deepseek-v4-flash",
                api_key="dummy_key",
            )
        )

    assert chunks == ["Fallback answer"]
    assert mock_client.chat.completions.create.call_count == 4
    assert (
        mock_client.chat.completions.create.call_args.kwargs["model"]
        == "qwen/qwen2.5-coder-32b-instruct"
    )


def test_stream_chat_continues_partial_answer_on_capacity_fallback():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    def partial_stream():
        yield SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    delta=SimpleNamespace(content="First half"),
                    finish_reason=None,
                )
            ],
        )
        raise Exception(
            "ResourceExhausted: Worker local total request limit reached (367/48)"
        )

    fallback_stream = iter(
        [
            SimpleNamespace(
                usage=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=" and second half"),
                        finish_reason="stop",
                    )
                ],
            )
        ]
    )
    provider = NvidiaProvider()
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        partial_stream(),
        fallback_stream,
    ]

    with (
        patch.object(provider, "_client", return_value=mock_client),
        patch("time.sleep") as sleep,
    ):
        chunks = list(
            provider.stream_chat(
                [{"role": "user", "content": "Explain this"}],
                "deepseek-ai/deepseek-v4-flash",
                api_key="dummy_key",
            )
        )

    assert chunks == ["First half", " and second half"]
    sleep.assert_not_called()
    fallback_call = mock_client.chat.completions.create.call_args.kwargs
    assert fallback_call["model"] == "qwen/qwen2.5-coder-32b-instruct"
    assert fallback_call["messages"][-2] == {
        "role": "assistant",
        "content": "First half",
    }
    assert fallback_call["messages"][-1] == {
        "role": "user",
        "content": _CONTINUE_PROMPT,
    }


def test_capacity_cooldown_skips_repeated_deepseek_probe():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    provider = NvidiaProvider()
    provider._mark_capacity_cooldown("deepseek-ai/deepseek-v4-flash")
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Immediate fallback", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=None,
    )

    with patch.object(provider, "_client", return_value=mock_client):
        result = provider.chat(
            [{"role": "user", "content": "Hello again"}],
            "deepseek-ai/deepseek-v4-flash",
            api_key="dummy_key",
        )

    assert result.endswith("Immediate fallback")
    assert mock_client.chat.completions.create.call_count == 1
    assert (
        mock_client.chat.completions.create.call_args.kwargs["model"]
        == "qwen/qwen2.5-coder-32b-instruct"
    )


def test_nemotron_ultra_capacity_uses_default_fallback():
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    provider = NvidiaProvider()
    mock_client = MagicMock()
    capacity_error = Exception(
        "ResourceExhausted: Worker local total request limit reached (32/32)"
    )
    fallback_response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="Updated document", tool_calls=None),
                finish_reason="stop",
            )
        ],
        usage=None,
    )
    mock_client.chat.completions.create.side_effect = [
        capacity_error,
        capacity_error,
        capacity_error,
        fallback_response,
    ]

    with (
        patch.object(provider, "_client", return_value=mock_client),
        patch("time.sleep"),
    ):
        result = provider.chat(
            [{"role": "user", "content": "Edit this Word document"}],
            "nvidia/nemotron-3-ultra-550b-a55b",
            api_key="dummy_key",
        )

    assert "`nvidia/nemotron-3-ultra-550b-a55b` is at capacity" in result
    assert result.endswith("Updated document")
    assert (
        mock_client.chat.completions.create.call_args.kwargs["model"]
        == "qwen/qwen2.5-coder-32b-instruct"
    )
