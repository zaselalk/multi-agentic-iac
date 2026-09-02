# Retriever Setup

## Requirements

Please make sure you have `iac-eval` conda environment activated and you are in the `retriever/` folder before executing any of the following commands.

Note: You can run `./setup.sh` for dependency check/setup and executing the following steps.

## Auth

The retriever grounds through the same Azure AI Foundry project used for generation (`foundry:<deployment-name>` models in `evaluation/eval.py`) — one endpoint and key, plus a deployment name each for the embedding model (indexing/retrieval) and the chat model (query generation). Set, or you'll be prompted for:

- `AZURE_AI_FOUNDRY_ENDPOINT` — the Foundry project's target URI, e.g. `https://<project>.services.ai.azure.com/models`
- `AZURE_AI_FOUNDRY_API_KEY`
- `AZURE_AI_FOUNDRY_EMBEDDING_MODEL` — an embedding model deployed in your Foundry project, e.g. `text-embedding-3-large`
- `AZURE_AI_FOUNDRY_RETRIEVER_MODEL` — a chat model deployed in your Foundry project, e.g. `gpt-4.1-mini`

All four can be set in a `.env` file at the repo root — see `../.env.example`.

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
