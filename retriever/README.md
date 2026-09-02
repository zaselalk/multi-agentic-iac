# Retriever Setup

## Requirements

Please make sure you have `iac-eval` conda environment activated and you are in the `retriever/` folder before executing any of the following commands.

Note: You can run `./setup.sh` for dependency check/setup and executing the following steps.

## Auth

The retriever grounds through the same Azure AI Foundry project used for generation (`foundry:<deployment-name>` models in `evaluation/eval.py`) — one endpoint and key, plus a deployment name each for the embedding model (indexing/retrieval) and the chat model (query generation). Set, or you'll be prompted for:

- `AZURE_AI_FOUNDRY_ENDPOINT` — the Foundry resource's **model inference** endpoint, shaped `https://<resource-name>.services.ai.azure.com/models`. Find it in the Foundry portal under your project's **Models + endpoints** page — **not** the project endpoint (`.../api/projects/<name>`) shown on the project's Overview page; that one is for the Azure AI Projects/Agents SDK and doesn't accept model inference calls. Passing it in fails fast with a clear error (rather than the Azure API's own generic `(BadRequest) API version not supported`, which is what a project endpoint actually returns here).
- `AZURE_AI_FOUNDRY_API_KEY`
- `AZURE_AI_FOUNDRY_EMBEDDING_MODEL` — an embedding model deployed in your Foundry project, e.g. `text-embedding-3-large`
- `AZURE_AI_FOUNDRY_RETRIEVER_MODEL` — a chat model deployed in your Foundry project, e.g. `gpt-4.1-mini`

All four can be set in a `.env` file at the repo root — see `../.env.example`.

If you still hit `(BadRequest) API version not supported` with a correct model-inference endpoint, set `AZURE_AI_FOUNDRY_API_VERSION` (optional, also in `.env.example`) — the `azure-ai-inference` SDK defaults to `2024-05-01-preview`, which some deployments reject. Try a plain Azure OpenAI date version instead, e.g. `2024-06-01`.

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
