"""Isolated OpenAI-compatible structured-output client for future AI features."""

import json
from typing import TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError


ResponseModel = TypeVar("ResponseModel", bound=BaseModel)


class LLMProviderError(RuntimeError):
    """A request, provider response, or schema validation failed."""


class LLMProvider:
    """A synchronous client with no access to the database or Telegram API."""

    def __init__(
        self,
        *,
        api_key: str,
        model_name: str | list[str],
        base_url: str,
        timeout_seconds: float,
        max_output_tokens: int,
        max_response_bytes: int,
    ) -> None:
        self._api_key = api_key
        model_names = [model_name] if isinstance(model_name, str) else model_name
        self._model_names = tuple(
            dict.fromkeys(
                name.strip()
                for item in model_names
                for name in item.split(",")
                if name.strip()
            )
        )
        if not self._model_names:
            raise ValueError("At least one LLM model must be configured")
        self._endpoint = f"{base_url.rstrip('/')}/chat/completions"
        self._timeout_seconds = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._max_response_bytes = max_response_bytes

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
        max_output_tokens: int | None = None,
    ) -> ResponseModel:
        """Generate and validate a strictly schema-shaped JSON response."""
        last_error: LLMProviderError | None = None
        for model_name in self._model_names:
            try:
                return self._generate_json_with_model(
                    model_name=model_name,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    response_model=response_model,
                    max_output_tokens=max_output_tokens,
                )
            except LLMProviderError as error:
                last_error = error

        assert last_error is not None
        raise LLMProviderError(
            f"All configured LLM models failed ({', '.join(self._model_names)}): {last_error}"
        ) from last_error

    def _generate_json_with_model(
        self,
        *,
        model_name: str,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ResponseModel],
        max_output_tokens: int | None,
    ) -> ResponseModel:
        """Make one attempt for one model."""
        output_limit = max_output_tokens or self._max_output_tokens
        if output_limit < 1:
            raise ValueError("max_output_tokens must be positive")
        output_limit = min(output_limit, self._max_output_tokens)
        schema = response_model.model_json_schema()
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": output_limit,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__.lower(),
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {"require_parameters": True},
        }
        request = Request(
            self._endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                raw_response = response.read(self._max_response_bytes + 1)
        except HTTPError as error:
            raise LLMProviderError(f"LLM provider returned HTTP {error.code}.") from error
        except (URLError, TimeoutError) as error:
            raise LLMProviderError("LLM provider request failed or timed out.") from error

        if len(raw_response) > self._max_response_bytes:
            raise LLMProviderError("LLM provider response exceeded the size limit.")
        try:
            response_payload = json.loads(raw_response)
            content = response_payload["choices"][0]["message"]["content"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
            raise LLMProviderError("LLM provider returned an invalid response.") from error
        if content is None or content == "":
            raise LLMProviderError("LLM provider returned an empty response.")
        if not isinstance(content, str):
            raise LLMProviderError("LLM provider returned non-text JSON content.")
        try:
            return response_model.model_validate_json(content)
        except ValidationError as error:
            first_error = error.errors()[0]
            location = ".".join(str(part) for part in first_error["loc"])
            raise LLMProviderError(
                "LLM provider response does not match the schema "
                f"at {location}: {first_error['msg']}."
            ) from error
