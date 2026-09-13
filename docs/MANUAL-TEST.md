# Testing this by hand

Every command below was run on this machine, in this order, against the
current checkout. The outputs quoted are real outputs, not illustrations.

There are four levels, cheapest first. The first two need no model, no
network and no credentials.

---

## 0. Is anything missing?

```shell
which terraform opa node   # all three optional-but-wanted
ls .env                    # Azure AI Foundry creds; only level 3 needs them
```

`terraform` and `opa` missing is not a crash: each validator reports
`skipped` rather than `pass`, which is the honest answer and is visible in
`/health`.

> **The `mcp-server/venv` in this checkout is a Windows venv** (`Scripts/`,
> not `bin/`) and cannot run here. Use the Linux venv from this repo for both
> repos: `/workspaces/Research/multi-agentic-iac/venv/bin/python`. It is the
> one with `python-hcl2` installed.

---

## 1. Unit tests — the compiler and the importer (2 seconds, no model)

```shell
cd ../mcp-server
/workspaces/Research/multi-agentic-iac/venv/bin/python -m unittest discover -s tests -t .
```

```
............................
Ran 28 tests in 0.506s

OK
```

28 tests: 12 round-trip, 16 import. Run these under the system `python3`
instead and 14 will report `skipped` — that is the `hcl2` optional dependency
being absent, not a failure.

---

## 2. The benchmark — 27 seeded faults (no model, free, reproducible)

```shell
cd ../multi-agentic-iac
./venv/bin/python -m benchmark.run --fault public_acl   # one class, ~1 min
./venv/bin/python -m benchmark.run                      # all 27
./venv/bin/python -m benchmark.run --ablate             # + the ablation table
```

It prints the corpus baseline first and **refuses to score anything if the
corpus is not clean**, because a base graph that already violates something
makes every number the sum of two effects.

Compare what you get against the committed run in
[benchmark/RESULTS.md](../benchmark/RESULTS.md) — that file exists to be
diffed. Expect detection 100%, attribution 100%, nodes touched 0.

To fill the `Repaired` column you need the model:

```shell
./venv/bin/python -m benchmark.run --model --fault dependency_cycle
```

That costs money and is not reproducible run to run, which is why it is not
the default.

---

## 3. The live stack by hand (needs `.env`)

```shell
./venv/bin/uvicorn orchestrator.server:app --port 8080
```

### 3a. What can actually prove anything

```shell
curl -s localhost:8080/health | python3 -m json.tool
```

Ten MCP tools, and a validator block that told the truth on this machine:
`schema` available, `policy` available with five `.rego` files, `deploy`
available, `cost` **unavailable — "not implemented: no price book
configured."** A missing validator says so rather than silently passing.

### 3b. Import somebody else's Terraform

This is the interesting one, because it is the case the system does *not*
control. Write a file with four things in it the importer must treat
differently:

```shell
cat > /tmp/sample.tf <<'EOF'
variable "env" {
  type    = string
  default = "dev"
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  tags = {
    Name = "main-vpc"
    Env  = var.env
  }
}

resource "aws_subnet" "app" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"
}

resource "aws_s3_bucket" "assets" {
  bucket = "group10-assets"
  acl    = "public-read"
}

resource "aws_instance" "worker" {
  count         = 3
  ami           = "ami-0abcdef1234567890"
  instance_type = "t3.micro"
}

resource "aws_glacier_vault" "archive" {
  name = "cold-storage"
}
EOF

python3 - <<'PY'
import json, urllib.request
tf = open("/tmp/sample.tf").read()
body = json.dumps({"name": "Import smoke", "terraform": tf}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    "http://localhost:8080/projects/import/terraform", body,
    {"Content-Type": "application/json"}))
d = json.load(r)
print("project:", d["project"]["id"])
print("nodes:", [(n["id"], n["type"]) for n in d["nodes"]])
print(json.dumps(d["import"], indent=2))
PY
```

**What to look for.** Five resources in, three on the canvas, and the other
two *named*:

```json
"coverage": { "resources_in_file": 5, "imported": 3, "unmapped": 1, "refused": 1 },
"unmapped": [ { "terraform_type": "aws_glacier_vault", "name": "archive" } ],
"refused":  [ { "terraform_type": "aws_instance", "name": "worker",
                "reason": "count makes one block into many; a node is one resource." } ]
```

The refusal is the point. `count = 3` imported as one node would look
complete and be wrong, so it is declined out loud. `var.env` survives inside
the tags as `@raw:var.env`, and the `variable "env"` declaration comes across
into project settings — without it the compiled HCL would reference a
variable nobody declared.

### 3c. Ask the graph to prove itself — no model, no edits

```shell
curl -sX POST localhost:8080/projects/<id>/verify | python3 -m json.tool
```

Took ~10s here, because a real `terraform plan` runs offline inside it.
Observed:

```
deploy pass | schema pass | policy FAIL | cost skipped
roundTrip: equivalent=true, hcl_match=true, resources=5, differences=[]

[error]   policy_violation/s3_public_acl  node=assets  attr=acl
[warning] policy_violation/s3_versioning  node=assets  attr=versioning
[warning] harmonization/registry_coverage node=assets
```

Two things worth noticing. The error carries **`node_id` and `attribute`**,
so it can be drawn on the node that caused it — that is the attribution the
benchmark measures. And the `registry_coverage` *warning* admits that `acl`
is passed through unchecked rather than pretending the registry knows it.

### 3d. The headline behaviour: intent is held, not reversed

The imported graph has `acl = "public-read"` — somebody's decision, and a
policy violation. Now ask for something unrelated:

```shell
python3 - <<'PY'
import json, urllib.request
d = json.load(open("imported.json"))   # saved from 3b
body = json.dumps({"message": "Add a private S3 bucket called group10-logs for access logs.",
                   "nodes": d["nodes"], "edges": d["edges"]}).encode()
r = urllib.request.urlopen(urllib.request.Request(
    "http://localhost:8080/projects/<id>/chat", body,
    {"Content-Type": "application/json"}), timeout=300)
o = json.load(r)
print(o["chatResponse"])
print("repairs:", o["repairs"], "| applied:", o["applied"])
print(json.dumps(o["proposal"]["patch"], indent=2))
PY
```

What came back here:

> I have added a private S3 bucket named group10-logs for access logs. […]
> **I have left assets as you asked**, but s3_public_acl rejects it […]
> Remove the acl attribute. Grant access with a bucket policy or CloudFront
> origin access control instead — **take that fix, or keep what you asked
> for.**

```json
{ "node_id": "assets", "attribute": "acl",
  "current": "public-read", "proposed": null, "rule": "s3_public_acl" }
```

`repairs: 0`. The bucket got added, the human's `public-read` is **still
there**, the fix is on the table as a patch the human can apply, and
`roundTrip.equivalent` is still `true` across eight resources. A system that
quietly set `acl = null` here would score better on the policy validator and
would be the wrong system.

To see the other half, apply it:

```shell
curl -sX POST localhost:8080/projects/<id>/proposal \
     -H 'Content-Type: application/json' -d '{"accept": true}'
```

### 3e. Clean up

```shell
curl -sX DELETE localhost:8080/projects/<id>
```

Projects live in `.visor/projects` and are gitignored, so leaving them costs
nothing but clutter.

---

## 4. The canvas

**Both servers have to be running, and the canvas is slow to start.**

```shell
# terminal 1 - the orchestrator, first
cd multi-agentic-iac && ./venv/bin/uvicorn orchestrator.server:app --port 8080

# terminal 2 - the canvas
cd visual-devops-builder && npm run dev        # node_modules already present
```

`npm run dev` returns the prompt immediately and **is not ready yet**. On this
machine Turbopack took **73s** to print `Ready`, and the first request to `/`
took another 26s to compile. Connection refused before then is the expected
behaviour, not a fault. Wait for this line before opening a browser:

```
✓ Ready in 72.9s
```

or poll for it:

```shell
until curl -sf -o /dev/null http://localhost:3000/; do :; done && echo up
```

Then open <http://localhost:3000>.

**Check the whole chain, not just the page.** The canvas talks to the
orchestrator server-side through one proxy route, `/api/visor/[...path]`, so
the browser never contacts port 8080 itself:

```shell
curl -s http://localhost:3000/api/visor/health     # -> the orchestrator's health JSON
```

If that returns the health document, the full path — browser → Next → proxy →
orchestrator → MCP server — is working. If the orchestrator is down, the UI
says so in plain language rather than failing silently.

> **In a devcontainer**, port 3000 has to be forwarded out of the container to
> reach a browser on the host. `.devcontainer/devcontainer.json` now declares
> `"forwardPorts": [3000, 8080]`; that takes effect on a container rebuild, and
> in the meantime VS Code's *Ports* panel will forward it (it usually
> auto-detects a new listener). Next binds `:::3000` so forwarding works;
> uvicorn binds `127.0.0.1:8080` only, which is fine because nothing outside
> the container needs it.

> **HMR does not work on this mount.** Edits to canvas source need a dev server
> restart — and another 70s — before they show up. Verify a change landed by
> looking at the served HTML, not by trusting a hot reload.

Worth doing by hand, because none of it is visible from `curl`:

1. **Drag a resource out, connect two nodes** — the Terraform pane rewrites
   itself on every change, and edges become real references, not text.
2. **Drop a `.tf` file onto the canvas** — the import dialog shows the same
   coverage report from 3b, including what it refused.
3. **Set a bucket's ACL to `public-read`** — the node goes red, and the
   finding is drawn *on that node*, not in a log.
4. **Ask the chat to delete something** — a breakpoint stops the turn and
   asks first. Nothing is written until you approve; the reply says what the
   agent wanted to do.
5. **Watch for a ghosted node** — a proposed change renders as a ghost chip
   with the patch attached, which is 3d with a UI on it.

---

## What this does *not* test

No `terraform apply` — nothing is ever deployed, so "it planned" is the
strongest claim available. Drift is measured against the last compile, not
against real cloud state. Cost is unimplemented and says so. And there is no
text-only baseline yet, which is why no comparative claim is made anywhere in
the repo. All four are written up in [FUTURE-WORK.md](FUTURE-WORK.md).
