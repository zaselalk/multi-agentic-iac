# Retriever Setup

## Requirements

Please make sure you have `iac-eval` conda environment activated and you are in the `retriever/` folder before executing any of the following commands.

Note: You can run `./setup.sh` for dependency check/setup and executing the following steps.

## Auth

The retriever grounds via an Azure OpenAI resource (one chat deployment for query generation, one embedding deployment for indexing/retrieval). Set, or you'll be prompted for:

- `AZURE_OPENAI_ENDPOINT` — e.g. `https://<resource>.openai.azure.com/`
- `AZURE_OPENAI_API_KEY`
- `AZURE_OPENAI_EMBEDDING_DEPLOYMENT` — e.g. `text-embedding-ada-002`
- `AZURE_OPENAI_LLM_DEPLOYMENT` — e.g. `gpt-35-turbo`
- `AZURE_OPENAI_API_VERSION` — optional, defaults to `2024-02-01`

This is independent of the `AZURE_AI_FOUNDRY_ENDPOINT`/`AZURE_AI_FOUNDRY_API_KEY` used for `foundry:<deployment-name>` generation models in `evaluation/eval.py` — Azure AI Foundry's unified model-catalog endpoint (used for generation) and an Azure OpenAI resource (used here for embeddings) are different Azure resource types with separate credentials, even when both live under the same Foundry project.

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
