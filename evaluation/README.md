# MACOG: Evaluation

The MACOG pipeline:
- Orchestrates cooperating agents (requirements, architecture, IR synthesis, HCL generation, verification).
- Grounds with RAG, emits a typed JSON IR, generates Terraform HCL, then self-verifies via terraform plan and OPA Rego.

## Usage guide

All commands assume you are in the `evaluation` directory, and that you have activated the env:

```bash
conda activate iac-eval
```

Note: You can run `./setup.sh` for dependency check/setup.

Please run the following scripts in order. Note that the main evaluation pipeline will generate the base results, that will be used by the other scripts (except for "Complete dataset measurements") to calculate certain metrics (e.g., Pass@K or LLM-judge). 

### Main evaluation pipeline

#### 🚀 Quick Start Demo Run

The following will default to a sample size of 1 per task, and perform the evaluation for WizardCoder33B (via Replicate) only, but only for a subset (2 rows) of our main dataset. Useful for testing the functionality of the benchmark. 

```bash
python3 eval.py --config=config.json --quick-test
```

#### 🔥 Quick Start

The following will default to a sample size of 1 per task, and perform the evaluation for WizardCoder33B (via Replicate) only. This will perform the evaluation on all rows in the dataset, which can take a significant amount of time. 

```bash
python3 eval.py --config=config.json
```

#### ✅ Multi-agent mode (recommended)

Use the multi-agent strategy (our main approach) with the -e multi-agent flag.

```bash
python3 eval.py --config=config.json -e multi-agent
```

Or specify models directly:

```bash
python3 eval.py -m gemini-2.5-pro -e multi-agent -s 1
```

#### Supported models and flags
- OpenAI: 
  - GPT‑3.5: -m gpt3.5
  - GPT‑4: -m gpt4
  - GPT‑5: -m gpt5
- Google Gemini:
  - Gemini 1.0 Pro: -m gemini-1.0-pro
  - Gemini 2.5 Pro: -m gemini-2.5-pro
  - Gemini 2.0 Flash: -m gemini-2.0-flash

Examples:
```bash
# Run multi-agent with GPT-5
python3 eval.py -m gpt5 -e multi-agent -s 1

# Run multi-agent with Gemini 2.5 Pro and 2.0 Flash
python3 eval.py -m gemini-2.5-pro,gemini-2.0-flash -e multi-agent -s 1
```

Auth:
- OpenAI models require OPENAI_API_KEY.
- Gemini models require GOOGLE_API_KEY.

#### Instructions

This function takes in data from the `data/` folder, and the evaluation results are written to the respective model folders (e.g., `/tmp/gpt4/` stores the temporary evaluated results, while `/results/gpt4` stores the final results).

Options for prompt-enhancement-strategy: COT, FSP, RAG, multi-turn, multi-agent (recommended)

Specify the number of samples per task and evaluation models list using command line options (`python3 eval.py --help` for help) or config file with `python3 eval.py --config=PATH_TO_FILE` to your desired value, and run the evaluation pipeline using:

```bash
python3 eval.py [command-options]
```

<!-- 💡 -->

> :exclamation: **Note**
> 1. If no other values are specified, the evaluation is defaulted to run on all models in the models list with a sample size of 20 per task.
> 2. If the script unexpectedly stops (e.g., due to an unforeseen error), you can directly rerun the script. It will continue where it left off. 

### LLM judge pipeline

This currently only applies the GPT4-single LLM-judge metric onto the evaluated datasets. Outputs in `../results/<model>/llm-judge-evaluation-metric/`

```bash
python3 llm-judge-eval.py gpt4 llm-single
```

#### Complete dataset measurements:
This script outputs a few json files which give us the difficulty level and resource distributions. 
This script also reads from `data/` and outputs the same dataset but with filled in "Difficulty" and "Resource" values, in `misc/complete-dataset-measurement/complete-dataset`. 
```bash
python3 misc/complete-dataset-measurement/complete-dataset-measurement.py
```

### Ablation calculation
This script mainly calculates other metrics such as BLEU, score by difficulty, accuracy, etc. 
This reads from `data`, and `evaluation/results` and outputs an `input_composition_dict.json` that gives the files that will be processed, and also incrementally outputs an `output_composition_dict.json` that contains the results.

This script assumes that the "Difficulty" and "Resource" columns of the dataset CSV file are properly filled; if this is not the case (e.g., new version of the dataset), please run the above script once, and move the resulting dataset CSV file manually to the `data` directory. 

```bash
python3 misc/ablation/ablation-iac-eval-pipeline.py
```

#### Ablation LLM-judge related calculation:
This script calculates LLM judge metrics given results from LLM judge in `../results/<model>/llm-judge-evaluation-metric/`.
This reads from `../results/<model>/llm-judge-evaluation-metric/`, and outputs an `input_composition_dict.json` that gives the files that will be processed, and also incrementally outputs an `output_composition_dict.json` that contains the results. 
```bash
python3 misc/ablation-judge/ablation-llm-judge.py
```

#### Ablation Pass@k related calculation:
This script calculates Pass@k metrics given results in `../results`.
This reads from `../results/`, and outputs an `input_composition_dict.json` that gives the files that will be processed, and also incrementally outputs an `pass-k-output_composition_dict.json` that contains the results. 

Make sure that the value of the command line option `n` is set to below or equal to the number of evaluation samples that exist in `../results`, e.g., if GPT-4 had 2 generated samples, then `n<=2`. 
```bash
python3 misc/ablation-multiple-sample/ablation-multiple-sample.py -n 20 # N refers to the number of samples. 
```

### Sagemaker usage (for MagiCoder-S-CL-7B evaluation)
This deploys a AWS SageMaker instance inference model and endpoint, running MagiCoder-S-CL-7B, that we can then later call for evaluation. 

```bash
python3 misc/sagemaker_setup/sagemaker-magicoder-s-cl-7b-deploy.py
```
