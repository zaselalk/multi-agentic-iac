# Retriever Setup

## Requirements

Please make sure you have `iac-eval` conda environment activated and you are in the `retriever/` folder before executing any of the following commands.

Note: You can run `./setup.sh` for dependency check/setup and executing the following steps.

## Auth

The retriever grounds through the same Azure AI Foundry project used for generation (`foundry:<deployment-name>` models in `evaluation/eval.py`) — one endpoint and key, plus a deployment name each for the embedding model (indexing/retrieval) and the chat model (query generation). Set, or you'll be prompted for:

- `AZURE_AI_FOUNDRY_ENDPOINT` — the Foundry resource's **model inference** endpoint, and it must literally end in `/models`: `https://<resource-name>.services.ai.azure.com/models`. Find it in the Foundry portal under your project's **Models + endpoints** page. Two common mistakes, both caught locally with a clear error instead of a live 404:
  - The project endpoint (`.../api/projects/<name>`) shown on the project's Overview page — that's for the Azure AI Projects/Agents SDK, a different API surface.
  - The bare resource URL without the `/models` suffix (`https://<resource-name>.services.ai.azure.com`) — `azure-ai-inference` appends its route (`/embeddings`, `/chat/completions`, ...) directly onto whatever string you give it; it does not add `/models` itself.
- `AZURE_AI_FOUNDRY_API_KEY`
- `AZURE_AI_FOUNDRY_EMBEDDING_MODEL` — an embedding model deployed in your Foundry project, e.g. `text-embedding-3-large`. Must match an actual deployment name exactly, or the call 404s.
- `AZURE_AI_FOUNDRY_RETRIEVER_MODEL` — a chat model deployed in your Foundry project, e.g. `gpt-4.1-mini`. Same deployment-name requirement.

All four can be set in a `.env` file at the repo root — see `../.env.example`.

If you hit `(BadRequest) API version not supported` with an endpoint that already passes the checks above, set `AZURE_AI_FOUNDRY_API_VERSION` (optional, also in `.env.example`) — the `azure-ai-inference` SDK defaults to `2024-05-01-preview`, which some deployments reject. Try a plain Azure OpenAI date version instead, e.g. `2024-06-01`.

## Download

```shell
git clone https://github.com/hashicorp/terraform-provider-aws.git
```

## Usage

The following script will:

1. Ask LLM to generate a list of prompts to search for (``generate_prompt_for_index``).

2. Use the generated list of prompts to query database (`query_documents`)

```shell
python3 llama_index_retriever.py
```

Note: 429 errors will cause retry and delay. This will take a while, but don't worry!
