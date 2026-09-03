"""
Standalone MACOG entrypoint: one natural-language request in, Terraform HCL out.

This is the multi-agent orchestration from the evaluation pipeline, without the
benchmark around it - no dataset, no scoring, no results CSVs. It reuses
eval.py's prompt construction, retrieval and model dispatch directly, so what
you get here is what the pipeline would generate for the same intent.

    python3 generate.py "create an S3 bucket with versioning enabled"
    python3 generate.py -f request.txt -o main.tf
    echo "..." | python3 generate.py -
    python3 generate.py "..." --no-rag --validate
"""

import os
import sys
import subprocess
import tempfile
import shutil

import click

import eval as pipeline
import llama_index_retriever

HERE = os.path.dirname(os.path.abspath(__file__))
SYSTEM_PROMPT = os.path.join(HERE, "prompt-templates", "system-prompt.txt")
STORED_INDEX = os.path.join(HERE, "..", "retriever", "aws-index")
DOCS_PATH = os.path.join(
    HERE, "..", "retriever", "terraform-provider-aws", "website", "docs", "r"
)


def setup_model_credentials(model):
    """Set up only the client the chosen model needs (no AWS/Replicate prompts)."""
    if model.startswith("foundry:"):
        pipeline.setup_azure_foundry_client()
    elif model.startswith("gemini"):
        pipeline.set_google_credentials()
    elif model in ("gpt3.5", "gpt4", "gpt5"):
        pipeline.setup_gpt_client()


def terraform_validate(code):
    """Run terraform init + validate on the generated HCL. No AWS creds needed."""
    workdir = tempfile.mkdtemp(prefix="macog-validate-")
    try:
        with open(os.path.join(workdir, "main.tf"), "w") as f:
            f.write(code)
        init = subprocess.run(
            ["terraform", "init", "-backend=false", "-no-color"],
            cwd=workdir,
            capture_output=True,
            text=True,
        )
        if init.returncode != 0:
            return False, init.stderr or init.stdout
        result = subprocess.run(
            ["terraform", "validate", "-no-color"],
            cwd=workdir,
            capture_output=True,
            text=True,
        )
        return result.returncode == 0, result.stdout + result.stderr
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


@click.command()
@click.argument("request", required=False)
@click.option(
    "--file",
    "-f",
    "request_file",
    type=click.Path(exists=True, dir_okay=False),
    help="Read the request from a file instead of the command line.",
)
@click.option(
    "--model",
    "-m",
    default="foundry:gpt-4.1-mini",
    show_default=True,
    help="Generation model. Any eval.py model works, e.g. foundry:<deployment-name>.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    help="Write the HCL here instead of stdout.",
)
@click.option(
    "--no-rag",
    is_flag=True,
    default=False,
    help="Skip retrieval grounding (faster, no embedding calls, less accurate).",
)
@click.option(
    "--validate",
    is_flag=True,
    default=False,
    help="Run terraform init + validate on the result (no AWS credentials needed).",
)
@click.option(
    "--show-prompt",
    is_flag=True,
    default=False,
    help="Print the assembled multi-agent prompt to stderr before generating.",
)
def main(request, request_file, model, output, no_rag, validate, show_prompt):
    """Generate Terraform HCL from a natural-language REQUEST via multi-agent orchestration."""
    if request_file:
        with open(request_file) as f:
            request = f.read().strip()
    elif request == "-" or not request:
        if sys.stdin.isatty() and not request:
            raise click.UsageError("Provide a request argument, -f FILE, or pipe stdin.")
        request = sys.stdin.read().strip()

    if not request:
        raise click.UsageError("Empty request.")

    setup_model_credentials(model)

    with open(SYSTEM_PROMPT) as f:
        preprompt = f.read()

    knowledge = ""
    if not no_rag:
        click.echo("Grounding against Terraform AWS provider docs...", err=True)
        retriever = llama_index_retriever.Retriever(
            stored_index=STORED_INDEX, path=DOCS_PATH
        )
        knowledge = pipeline.rag_knowledge(retriever, request)

    prompt = pipeline.build_multi_agent_prompt(knowledge, request)
    if show_prompt:
        click.echo(prompt, err=True)

    click.echo(f"Generating with {model}...", err=True)
    text = pipeline.call_model(model, preprompt, prompt)
    _, code = pipeline.separate_answer_and_code(text, pipeline.DELIMITERS)

    if not code:
        click.echo("Model returned no HCL. Raw output:", err=True)
        click.echo(text, err=True)
        sys.exit(1)

    if validate:
        ok, details = terraform_validate(code)
        click.echo(
            f"terraform validate: {'passed' if ok else 'FAILED'}", err=True
        )
        if not ok:
            click.echo(details, err=True)

    if output:
        with open(output, "w") as f:
            f.write(code + "\n")
        click.echo(f"Wrote {output}", err=True)
    else:
        click.echo(code)


if __name__ == "__main__":
    main()
