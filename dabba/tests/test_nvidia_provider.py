from dabba.providers.nvidia_provider import NvidiaProvider


def test_glm_disables_thinking_by_default():
    params = NvidiaProvider()._build_params(
        [{"role": "user", "content": "Hello"}],
        "z-ai/glm-5.2",
        max_tokens=256,
    )

    assert params["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


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
