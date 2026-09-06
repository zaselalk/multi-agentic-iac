"""
Model access for the orchestrator.

Extracted from the IaC-Eval harness's eval.py, which used to own the Azure AI
Foundry client for the whole repo. The harness is gone; this is the part the
agents actually need - one chat client, plus the endpoint checks that turn two
common Foundry misconfigurations into readable errors instead of a 400 or a
404 from deep inside the SDK.
"""

import getpass
import os

from azure.ai.inference import ChatCompletionsClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

DEFAULT_MODEL = os.environ.get("VISOR_AGENT_MODEL", "gpt-4.1-mini")

_client = None


def validate_endpoint(endpoint: str):
    # A Foundry *project* endpoint (.../api/projects/<name>, for the Azure AI
    # Projects/Agents SDK) is easy to copy by mistake from the portal's
    # Overview page instead of the model inference endpoint (.../models, under
    # "Models + endpoints") that azure-ai-inference needs. Both "work" in that
    # they accept a request, so this fails fast with a clear message instead of
    # a cryptic "API version not supported" 400.
    if "/api/projects/" in endpoint:
        raise ValueError(
            f"AZURE_AI_FOUNDRY_ENDPOINT ({endpoint}) looks like a Foundry "
            "*project* endpoint, not the model inference endpoint. Use "
            "https://<resource-name>.services.ai.azure.com/models instead - "
            "find it in the Foundry portal under your project's "
            "'Models + endpoints' page."
        )
    # azure-ai-inference appends its operation route (/embeddings,
    # /chat/completions, ...) directly onto whatever string is given - it does
    # not add "/models" itself, so a Foundry resource endpoint
    # (*.services.ai.azure.com) missing that path segment 404s.
    host = endpoint.split("//", 1)[-1].split("/", 1)[0]
    if host.endswith(".services.ai.azure.com") and not endpoint.rstrip("/").endswith("/models"):
        raise ValueError(
            f"AZURE_AI_FOUNDRY_ENDPOINT ({endpoint}) is missing the '/models' "
            "path. Azure AI Foundry resource endpoints need it explicitly: "
            "https://<resource-name>.services.ai.azure.com/models"
        )


def setup_client() -> ChatCompletionsClient:
    """Build the Foundry chat client. Idempotent; called once at startup."""
    global _client
    if _client is not None:
        return _client

    if "AZURE_AI_FOUNDRY_ENDPOINT" not in os.environ:
        os.environ["AZURE_AI_FOUNDRY_ENDPOINT"] = input(
            "Enter Azure AI Foundry endpoint URL: "
        )
    if "AZURE_AI_FOUNDRY_API_KEY" not in os.environ:
        os.environ["AZURE_AI_FOUNDRY_API_KEY"] = getpass.getpass(
            "Enter Azure AI Foundry API key: "
        )

    validate_endpoint(os.environ["AZURE_AI_FOUNDRY_ENDPOINT"])

    # azure-ai-inference defaults to api-version=2024-05-01-preview, which not
    # every Foundry deployment accepts. AZURE_AI_FOUNDRY_API_VERSION overrides
    # it when needed.
    kwargs = {}
    api_version = os.environ.get("AZURE_AI_FOUNDRY_API_VERSION")
    if api_version:
        kwargs["api_version"] = api_version

    _client = ChatCompletionsClient(
        endpoint=os.environ["AZURE_AI_FOUNDRY_ENDPOINT"],
        credential=AzureKeyCredential(os.environ["AZURE_AI_FOUNDRY_API_KEY"]),
        **kwargs,
    )
    return _client


def client() -> ChatCompletionsClient:
    """The chat client, built on first use."""
    return _client if _client is not None else setup_client()
