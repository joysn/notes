# Kubernetes Operators & GitHub Actions ARC (Actions Runner Controller)

## Kubernetes Operators

### What is an Operator?

An Operator is a software extension to Kubernetes that uses **Custom Resources** to manage applications. It encodes the domain knowledge of a human operator (deploy, scale, heal, upgrade) into a controller that runs continuously.

### Key Building Blocks

| Concept | What it is |
|---------|-----------|
| **Custom Resource (CR)** | A new "kind" you add to the K8s API (e.g., `kind: RunnerScaleSet`) |
| **Custom Resource Definition (CRD)** | The schema that defines your CR (like a table DDL for the API) |
| **Controller** | A loop that watches CRs and reconciles actual state → desired state |
| **Operator** | Controller + CRD + domain logic, packaged together |

### The Control Loop (Reconcile)

```
┌─────────────────────────────────────────┐
│         Observe (watch API)             │
│              ↓                          │
│   Compare desired state vs actual state │
│              ↓                          │
│         Act (create/update/delete)      │
│              ↓                          │
│         Loop forever                    │
└─────────────────────────────────────────┘
```

The controller continuously:
1. **Observes** — watches the K8s API for changes to its CRs
2. **Diffs** — compares what *should* exist vs what *does* exist
3. **Acts** — creates Pods, Services, Jobs, etc. to close the gap

### What Operators Can Automate

- Deploying an application on demand
- Taking and restoring backups of application state
- Handling upgrades of application code alongside related changes (database schemas, configuration settings)
- Simulating failure in all or part of your cluster to test resilience
- Choosing a leader for a distributed application without an internal member election process

### Operator vs. Deployment/ReplicaSet

A Deployment/ReplicaSet gives you: "keep N pods alive." An Operator gives you: "keep the *application in a correct state*."

| Layer | ReplicaSet does this | Operator adds this |
|-------|---------------------|-------------------|
| Pod dies | Replaces it with a new pod | Deregisters the dead runner from GitHub, registers the new one, ensures no orphaned tokens |
| Pod is running but broken | Nothing (pod is "Ready") | Detects runner is stuck/unresponsive via external API, drains and replaces it |
| Job finishes | Nothing | Tears down the runner pod (ephemeral runners), scales down to save resources |
| Scaling | Fixed replica count (or HPA on CPU/memory) | Scales based on **external state** (e.g., queued GitHub jobs) that a ReplicaSet can't see |

---

## GitHub Actions ARC — Runner Scale Sets

### What is a Runner Scale Set?

A Runner Scale Set is the deployment unit in ARC — a named, autoscaled pool of self-hosted runners registered to a GitHub repository, organization, or enterprise. Deployed via Helm charts and managed by the ARC operator.

### Architecture Overview

```
┌─────────────────────────────────────────────────────┐  ┌──────────────────────────────────────────────┐
│         GITHUB (their infra)                        │  │           NTSK INFRASTRUCTURE (K8s)          │
│                                                     │  │                                              │
│  ┌───────────┐  ┌───────────────┐                   │  │  ┌────────────┐  ┌──────────┐  ┌───────────┐ │
│  │ Actions   │  │ Runner        │                   │  │  │ ARC        │  │ Listener │  │ Runner    │ │
│  │ Service   │  │ Registration  │                   │  │  │ Controller │  │ Pod      │  │ Pod(s)    │ │
│  │           │  │ Service       │                   │  │  │            │  │          │  │           │ │
│  └───────────┘  └───────────────┘                   │  │  └────────────┘  └──────────┘  └───────────┘ │
│  ┌───────────┐  ┌───────────────┐                   │  │                                              │
│  │ Job Queue │  │ GitHub UI /   │                   │  │  ┌────────────────────────────────────────┐  │
│  │           │  │ API + Checks  │                   │  │  │ Kubernetes API Server                  │  │
│  └───────────┘  └───────────────┘                   │  │  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘  └──────────────────────────────────────────────┘
```

### How ARC Maps to Operator Concepts

| Operator concept | ARC equivalent |
|-----------------|----------------|
| CRD | `RunnerScaleSet`, `AutoscalingRunnerSet`, `EphemeralRunnerSet` |
| Custom Resource | Your YAML declaring "I want 3-10 runners for repo X" |
| Controller | ARC's controller pod watching for workflow jobs |
| Reconcile loop | Scale runners up when jobs queue, scale down when idle |
| Domain knowledge | "How to register/deregister GitHub runners, handle graceful drain" |

### Scale Set Configuration

Key fields in the Helm values:

| Field | Purpose |
|-------|---------|
| `runnerScaleSetName` | The `runs-on:` label your workflows target |
| `githubConfigUrl` | Scope: repo, org, or enterprise |
| `minRunners` / `maxRunners` | Scaling bounds |
| `containerMode` | `dind`, `kubernetes`, or none |
| `template.spec` | Pod spec for runners (image, resources, volumes) |

### Scaling Configurations

| Config | Behavior |
|--------|----------|
| Both omitted | 0 → ∞ (unbounded, scales to zero when idle) |
| `minRunners: 5` | Always 5 warm runners ready, scales up from there |
| `maxRunners: 30` | Never exceed 30 concurrent runners |
| Both set to `0` | Drains — no new runners created |

Formula: `desired = minRunners + queued_jobs` (capped at `maxRunners`)

### Scale Set vs. Runner Group

- A **runner group** (GitHub concept) is an access-control boundary — "which repos can use these runners"
- A **scale set** (ARC/K8s concept) is a deployment unit — "a pool of pods with specific resources, scaling rules, and container mode"

You can have multiple scale sets in the same runner group (e.g., `linux-small` with 2 CPU, `linux-gpu` with a GPU node selector).

---

## End-to-End Control Flow

### Phase 1: Scale Set Registration (One-time setup)

```
NTSK K8s                                         GITHUB
─────────                                        ──────

helm install arc-runner-set ...
        │
        ▼
┌────────────┐                               ┌──────────────────┐
│ ARC        │───── POST /runner-groups ────▶│ Runner           │
│ Controller │      /scale-sets              │ Registration     │
│            │◀──── 201: scaleSetId ──────── │ Service          │
└────────────┘                               └──────────────────┘
        │                                          │
        │  (creates Listener pod)                  ▼
        ▼                                   ┌──────────────────┐
┌────────────┐                              │ GitHub UI:       │
│ Listener   │───── Long-poll session ─────▶│ "Scale set       │
│ Pod        │      (authenticated)         │  registered,     │
│            │      waiting for jobs...     │  0 runners idle" │
└────────────┘                              └──────────────────┘

API calls:
  1. Register scale set (name, runner group, labels)
  2. Acquire message session (long-poll channel for job assignments)
```

### Phase 2: Job Triggered → Runner Created

```
Developer pushes code / opens PR
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ GITHUB ACTIONS SERVICE                                      │
│                                                             │
│  1. Workflow triggered (push/PR/manual)                     │
│  2. Job parsed: runs-on: "my-k8s-runners"                   │
│  3. Job enters QUEUED state                                 │
│  4. GitHub UI: job shows "Queued" ⏳                        │
│  5. Actions service matches label → NTSK scale set          │
│  6. Assigns job to scale set → pushes to message session    │
└──────────────────────────────────┬──────────────────────────┘
                                   │
                job assignment message (long-poll response)
                                   │
                                   ▼
NTSK K8s ─────────────────────────────────────────────────────
                                   │
                        ┌──────────▼─────────┐
                        │ Listener Pod       │
                        │  Receives:         │
                        │   - jobId          │
                        │   - jobUrl         │
                        │   - runnerRequest  │
                        └──────────┬─────────┘
                                   │
                  (updates EphemeralRunnerSet CR via K8s API)
                                   │
                        ┌──────────▼─────────┐
                        │ ARC Controller     │
                        │  Reconcile loop:   │
                        │   desired=1 runner │
                        │   actual=0 runners │
                        │   → create pod     │
                        └──────────┬─────────┘
                                   │
                        ┌──────────▼─────────┐
                        │ K8s API Server     │
                        │  → schedules pod   │
                        │  → node pulls image│
                        │  → pod starts      │
                        └──────────┬─────────┘
                                   │
                        ┌──────────▼──────────┐
                        │ Runner Pod (started)│
                        └─────────────────────┘
```

### Phase 3: Runner Registration → Job Execution

```
NTSK K8s                                          GITHUB
─────────                                         ──────

┌────────────────┐                          ┌──────────────────┐
│ Runner Pod     │                          │ Runner           │
│                │                          │ Registration Svc │
│ 1. run.sh      │                          │                  │
│    starts      │                          │                  │
│                │                          │                  │
│ 2. Register    │── POST /runners ────────▶│ Creates runner   │
│    as JIT      │   (Just-In-Time token)   │ record           │
│    runner      │◀─ 200: runnerId ─────────│                  │
│                │                          └──────────────────┘
│                │                                 │
│                │                                 ▼
│                │                          ┌──────────────────┐
│                │                          │ GitHub UI:       │
│ 3. Poll for    │── GET /messages ────────▶│ Runner "idle" 🟢 │
│    job         │◀─ job payload ───────────│ Job → "In        │
│                │                          │ Progress" 🟡     │
│                │                          └──────────────────┘
│                │
│ 4. Execute     │
│    steps:      │
│    - checkout  │
│    - run cmds  │
│    - actions   │
│                │
│   DURING EXECUTION, runner calls          GitHub UI
│   GitHub API periodically:                (streaming)
│    • POST /live logs ─────────────────────▶ Live log output
│    • POST /timeline ──────────────────────▶ Step status updates
│    • POST /annotations ───────────────────▶ Warnings/errors
│    • PUT /artifacts ──────────────────────▶ Artifact storage
│    • GET/POST /caches ────────────────────▶ Cache service
│                │
└────────────────┘
```

### Phase 4: Job Completion → Cleanup

```
NTSK K8s                                          GITHUB
─────────                                         ──────

┌────────────────┐                           ┌──────────────────┐
│ Runner Pod     │                           │ Actions Service  │
│                │                           │                  │
│ 5. All steps   │── POST /complete ───────▶ │ Job → "Success"  │
│    finished    │   {result: "succeeded"}   │ or "Failed" ✅❌  │
│                │                           │                  │
│ 6. Deregister  │── DELETE /runners/{id} ──▶│ Runner removed   │
│    self        │                           │ from pool        │
│                │                           │                  │
│ 7. Process     │                           │ GitHub UI:       │
│    exits(0)    │                           │ "Run completed"  │
└───────┬────────┘                           │ Shows logs,      │
        │                                    │ duration, status │
        │ (pod terminates)                   └──────────────────┘
        ▼
┌────────────────┐
│ ARC Controller │
│                │
│ Watches pod:   │
│  phase=Succeed │
│                │
│ Reconcile:     │
│  desired=0     │
│  actual=1(done)│
│  → delete pod  │
│                │
│ Cleans up:     │
│  - Pod         │
│  - PVC (if any)│
│  - Secrets     │
└───────┬────────┘
        │
        ▼
┌────────────────┐                          ┌──────────────────┐
│ Listener Pod   │                          │ Actions Service  │
│                │                          │                  │
│ Acks job       │── ACK job complete ─────▶│ Updates stats:   │
│ completion     │                          │  - billable mins │
│                │                          │  - queue time    │
│ Resumes        │                          │  - run duration  │
│ long-poll...   │                          │                  │
│ (waiting for   │                          │ Triggers:        │
│  next job)     │                          │  - dependent jobs│
│                │                          │  - notifications │
│                │                          │  - status checks │
└────────────────┘                          └──────────────────┘
```

---

## Deep Dive: Runner Pod Registration Process

### CRD Hierarchy

```
AutoScalingRunnerSet          (user-facing, installed via Helm)
  └── EphemeralRunnerSet      (manages desired replica count)
       └── EphemeralRunner    (represents one runner instance)
            └── Runner Pod    (actual container executing the job)
```

### Component Responsibilities

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ NTSK KUBERNETES CLUSTER                                                         │
│                                                                                 │
│  ┌──────────────────────────────────┐                                           │
│  │ Controller Manager Pod           │                                           │
│  │                                  │                                           │
│  │  ┌────────────────────────────┐  │                                           │
│  │  │ AutoScalingRunnerSet Ctrl  │──┼──── Registers scale set with GitHub       │
│  │  └────────────────────────────┘  │                                           │
│  │  ┌────────────────────────────┐  │                                           │
│  │  │ AutoScaling Listener Ctrl  │──┼──── Creates/manages the Listener pod      │
│  │  └────────────────────────────┘  │                                           │
│  │  ┌────────────────────────────┐  │                                           │
│  │  │ EphemeralRunner Controller │──┼──── Requests JIT tokens, creates pods     │
│  │  └────────────────────────────┘  │                                           │
│  └──────────────────────────────────┘                                           │
│                                                                                 │
│  ┌──────────────────────────────────┐                                           │
│  │ Listener Pod                     │                                           │
│  │  - Long-polls GitHub Actions Svc │                                           │
│  │  - Patches EphemeralRunnerSet    │                                           │
│  │    via ServiceAccount/Role       │                                           │
│  └──────────────────────────────────┘                                           │
│                                                                                 │
│  ┌──────────────────────────────────┐                                           │
│  │ Runner Pod (ephemeral)           │                                           │
│  │  - Starts with JIT config ONLY   │                                           │
│  │  - NO PAT/App token on pod       │                                           │
│  │  - Registers, runs 1 job, dies   │                                           │
│  └──────────────────────────────────┘                                           │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Full Sequence: Job Assigned → Runner Pod Registered & Running

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Actions    │    │  Listener    │    │ K8s API +    │    │ Ephemeral    │    │  Runner      │
│   Service    │    │  Pod         │    │ EphRunnerSet │    │ Runner Ctrl  │    │  Pod         │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │                   │                   │
       │ ① "Job Available" │                   │                   │                   │
       │  (long-poll msg)  │                   │                   │                   │
       │──────────────────▶│                   │                   │                   │
       │                   │                   │                   │                   │
       │   ② ACK message   │                   │                   │                   │
       │◀──────────────────│                   │                   │                   │
       │                   │                   │                   │                   │
       │                   │ ③ PATCH           │                   │                   │
       │                   │   EphemeralRunner │                   │                   │
       │                   │   Set replicas+1  │                   │                   │
       │                   │──────────────────▶│                   │                   │
       │                   │                   │                   │                   │
       │                   │                   │ ④ Creates         │                   │
       │                   │                   │   EphemeralRunner │                   │
       │                   │                   │   resource        │                   │
       │                   │                   │──────────────────▶│                   │
       │                   │                   │                   │                   │
       │  ⑤ Request JIT    │                   │                   │                   │
       │    config token   │                   │                   │                   │
       │◀──────────────────────────────────────────────────────────│                   │
       │                   │                   │                   │                   │
       │  ⑥ Return         │                   │                   │                   │
       │    encoded_jit_   │                   │                   │                   │
       │    config         │                   │                   │                   │
       │──────────────────────────────────────────────────────────▶│                   │
       │                   │                   │                   │                   │
       │                   │                   │                   │ ⑦ Create Pod     │
       │                   │                   │                   │   with JIT config │
       │                   │                   │                   │   (retry up to 5x)│
       │                   │                   │                   │──────────────────▶│
       │                   │                   │                   │                   │
       │                   │                   │                   │                   │ ⑧ Pod starts
       │                   │                   │                   │                   │   run.sh
       │                   │                   │                   │                   │   --jitconfig
       │                   │                   │                   │                   │   ${encoded}
       │                   │                   │                   │                   │
       │  ⑨ Register with JIT token (runner identifies itself)    │                   │
       │◀─────────────────────────────────────────────────────────────────────────────│
       │                   │                   │                   │                   │
       │  ⑩ ACK registration (runnerId assigned)                  │                   │
       │─────────────────────────────────────────────────────────────────────────────▶│
       │                   │                   │                   │                   │
       │  ⑪ Long-poll for job details                             │                   │
       │◀─────────────────────────────────────────────────────────────────────────────│
       │                   │                   │                   │                   │
       │  ⑫ Dispatch job payload (steps, env, secrets refs)       │                   │
       │─────────────────────────────────────────────────────────────────────────────▶│
       │                   │                   │                   │                   │
       │                   │                   │                   │                   │ ⑬ Execute job
       │                   │                   │                   │                   │    steps...
       │                   │                   │                   │                   │
```

### Step-by-Step Explanation

| Step | Who | Does What | API Call |
|------|-----|-----------|----------|
| ① | GitHub Actions Service | Pushes "job available" to Listener's long-poll session | Internal (long-poll response) |
| ② | Listener Pod | Acknowledges receipt of the job message | HTTPS to Actions Service |
| ③ | Listener Pod | Patches EphemeralRunnerSet desired count +1 | K8s API (via ServiceAccount) |
| ④ | EphemeralRunnerSet | Creates a new EphemeralRunner CR | K8s internal reconcile |
| ⑤ | EphemeralRunner Controller | Requests a JIT config token for this specific runner | `POST /orgs/{org}/actions/runners/generate-jitconfig` |
| ⑥ | GitHub | Returns `encoded_jit_config` containing identity + credentials | Response to ⑤ |
| ⑦ | EphemeralRunner Controller | Creates the Runner Pod, injecting JIT config (retries up to 5x) | K8s API: create Pod |
| ⑧ | Runner Pod | Starts `run.sh --jitconfig ${encoded_jit_config}` | Local process |
| ⑨ | Runner Pod | Registers itself using the JIT token | `POST /actions/runners` (with JIT token) |
| ⑩ | GitHub | Confirms registration, assigns a runner ID | Response to ⑨ |
| ⑪ | Runner Pod | Opens long-poll connection waiting for job dispatch | HTTPS long-poll to Actions Service |
| ⑫ | GitHub | Sends full job payload (steps, variables, secret refs) | Long-poll response |
| ⑬ | Runner Pod | Executes workflow steps | Local execution |

### The JIT Config — What's Inside

The `encoded_jit_config` is a base64-encoded blob containing everything the runner needs to connect:

```
┌─────────────────────────────────────────────────────┐
│ encoded_jit_config (opaque to you, used by runner)  │
│                                                     │
│  • Runner name + ID (pre-registered with GitHub)    │
│  • Runner group assignment                          │
│  • Labels (matching NTSK scale set)                 │
│  • OAuth credentials (short-lived, scoped to this   │
│    runner only)                                     │
│  • Actions Service URL (endpoint to connect to)     │
│  • Runner scale set ID                              │
│                                                     │
│  DOES NOT CONTAIN:                                  │
│  • NTSK GitHub PAT                                  │
│  • NTSK GitHub App private key                      │
│  • Any org-wide credentials                         │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Security design**: The PAT/App token lives ONLY on the Controller. The runner pod gets a single-use, pre-scoped JIT token. If the pod is compromised, the attacker cannot register more runners or access your org-level credentials.

### The generate-jitconfig API Call (Step ⑤)

```
POST /orgs/{org}/actions/runners/generate-jitconfig
Authorization: Bearer <PAT or GitHub App installation token>

{
  "name": "arc-runner-set-rmrgw-runner-p9p5n",
  "runner_group_id": 1,
  "labels": ["self-hosted", "linux", "x64", "arc-runner-set"],
  "work_folder": "_work"
}

Response 201:
{
  "runner": {
    "id": 42,
    "name": "arc-runner-set-rmrgw-runner-p9p5n",
    "os": "linux",
    "status": "offline",
    "busy": false,
    "ephemeral": true,
    "labels": [...]
  },
  "encoded_jit_config": "eyJhbGciOi..."   ← this goes to the pod
}
```

Note: The runner is already **registered** on GitHub at this point (status: "offline"). The pod just needs to connect using the token.

### How JIT Config Reaches the Pod

```
┌─────────────────────────────────────────────────────────────┐
│ EphemeralRunner Controller                                  │
│                                                             │
│  1. Calls GitHub API → gets encoded_jit_config              │
│  2. Creates Pod spec:                                       │
│                                                             │
│     containers:                                             │
│     - name: runner                                          │
│       image: ghcr.io/actions/actions-runner:latest          │
│       command: ["/home/runner/run.sh"]                      │
│       args: ["--jitconfig", "eyJhbGciOi..."]                │
│       ─── OR ───                                            │
│       env:                                                  │
│       - name: ACTIONS_RUNNER_INPUT_JITCONFIG                │
│         value: "eyJhbGciOi..."                              │
│                                                             │
│  3. Pod scheduled → node pulls image → container starts     │
│  4. run.sh reads --jitconfig, skips config.sh entirely      │
│     (no interactive registration needed)                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Order of Operations: JIT Token FIRST, Then Pod Creation

The JIT config token is obtained **before** the pod is created. This is required because the token is baked into the pod spec itself (as args/env). The pod cannot exist without it.

```
Timeline:
─────────────────────────────────────────────────────────────────────────────

  ④ EphemeralRunner     ⑤ Controller calls     ⑥ GitHub returns       ⑦ Controller
     CR created            GitHub API:            response:              creates Pod
     (name known:          generate-jitconfig     {                      with JIT config
      "arc-runner-                                  runner: {             in args/env
       set-abc123")        { name: "...",             id: 42,
                             runner_group_id: 1,      status: "offline",
                             labels: [...] }          ephemeral: true
                                                    },
                                                    encoded_jit_config:
                                                      "eyJhbG..."
                                                  }
         │                      │                       │                    │
─────────┼──────────────────────┼───────────────────────┼────────────────────┼─────
         │                      │                       │                    │
         ▼                      ▼                       ▼                    ▼
   Runner name is         GitHub pre-registers     Runner exists on      Pod is created
   decided by K8s         the runner (offline)     GitHub BEFORE the     AFTER we have
   (from CR name)                                  pod even exists       the token
```

**Why this order?**
- The `generate-jitconfig` API both **registers the runner** AND returns the token in one call
- GitHub needs to know the runner name/labels/group upfront to allocate an ID
- The pod spec needs the token at creation time — you can't inject it after the fact
- If the pod later fails to start, the controller's finalizer deregisters the orphaned "offline" runner from GitHub

### Why JIT Token Exists — The Security Problem It Solves

The JIT token solves a **credential scoping problem**. Without it, you'd have to put your org-level PAT or GitHub App private key directly on the runner pod.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  WITHOUT JIT (traditional / naive approach)                              │
│                                                                          │
│  Controller has: PAT (admin:org scope)                                   │
│                     │                                                    │
│                     │  "Here, pod, use this to register yourself"         │
│                     ▼                                                    │
│  ┌──────────────────────────────────────┐                                │
│  │ Runner Pod                           │                                │
│  │                                      │                                │
│  │  Has: PAT (admin:org scope) 😱       │                                │
│  │                                      │                                │
│  │  If compromised, attacker can:       │                                │
│  │   • Register unlimited new runners   │                                │
│  │   • List all runners in the org      │                                │
│  │   • Delete other runners             │                                │
│  │   • Access org-level settings        │                                │
│  │   • Potentially pivot to other repos │                                │
│  └──────────────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────┐
│  WITH JIT                                                                │
│                                                                          │
│  Controller has: PAT (admin:org scope) — never leaves the controller     │
│                     │                                                    │
│                     │  Calls GitHub API: "pre-register runner X"          │
│                     │  Gets back: single-use JIT token (scoped to X)     │
│                     │                                                    │
│                     │  "Here, pod, use this to CONNECT as runner X"       │
│                     ▼                                                    │
│  ┌──────────────────────────────────────┐                                │
│  │ Runner Pod                           │                                │
│  │                                      │                                │
│  │  Has: JIT token (scoped, single-use) │                                │
│  │                                      │                                │
│  │  If compromised, attacker can:       │                                │
│  │   • Connect as THIS runner only      │                                │
│  │   • ...that's it                     │                                │
│  │                                      │                                │
│  │  Attacker CANNOT:                    │                                │
│  │   • Register new runners             │                                │
│  │   • See other runners                │                                │
│  │   • Access org settings              │                                │
│  │   • Reuse the token (it's one-shot)  │                                │
│  └──────────────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘
```

**Hotel analogy:**

| Concept | Hotel analogy |
|---------|--------------|
| PAT / GitHub App key | Master key card (opens every room) |
| JIT token | Room-specific key card (opens only room 42, expires at checkout) |
| Controller | Front desk (holds master, issues room keys) |
| Runner Pod | Hotel guest (only gets their room key) |

**Three design goals JIT achieves:**

1. **Least privilege** — the pod only gets credentials to do one thing: connect as one pre-registered runner
2. **No config step** — traditional `config.sh` creates a `.credentials` file with long-lived RSA keys; JIT skips all of that
3. **Ephemeral by design** — token is meaningless after the pod connects; there's nothing to steal that's reusable

**What would happen without JIT?**

- **Put the PAT on every pod** → massive blast radius if any pod is compromised (supply-chain attack in a workflow step, malicious action, etc.)
- **Use a registration token** → better, but it's reusable for 1 hour and anyone who intercepts it can register arbitrary runners into your org
- **Mount a shared secret** → same problem, plus secret rotation becomes a nightmare at scale

JIT eliminates all of these by making the controller the **single trust boundary** — the only component that ever touches your org credentials.

### Traditional Registration vs. JIT Registration

| Aspect | Traditional (config.sh) | JIT (ARC) |
|--------|------------------------|-----------|
| Registration token | 1-hour lived, reusable | N/A — runner pre-registered |
| Config step | `./config.sh --url ... --token ...` | Skipped entirely |
| Credentials on pod | `.credentials` file (RSA keys) | JIT token in args/env only |
| Runner identity | Created during config.sh | Pre-created by Controller via API |
| Reuse | Runner persists across jobs | One job, then destroyed |
| Compromise blast radius | Can re-register, has long-lived creds | Token is single-use, scoped |

### Why Is a Credential (JIT or Traditional) Required At All?

The credential is NOT just for the initial "registration" step. It's the runner's **authenticated identity for EVERY API call throughout its entire lifetime**:

```
Runner Pod lifecycle — EVERY arrow is an authenticated HTTPS call:

    ┌────────────────────────────────────────────────────────────┐
    │  "Who are you? Prove it." ← GitHub asks this EVERY TIME    │
    └────────────────────────────────────────────────────────────┘

    Runner Pod                                     GitHub
        │                                            │
        │── "I'm runner 42" (credential) ───────────▶│ Connect & get job
        │── "I'm runner 42" (credential) ───────────▶│ Stream log line 1
        │── "I'm runner 42" (credential) ───────────▶│ Stream log line 2
        │── "I'm runner 42" (credential) ───────────▶│ Mark step 1 done ✓
        │── "I'm runner 42" (credential) ───────────▶│ Stream log line 3
        │── "I'm runner 42" (credential) ───────────▶│ Upload artifact
        │── "I'm runner 42" (credential) ───────────▶│ Mark step 2 done ✓
        │── "I'm runner 42" (credential) ───────────▶│ Save cache
        │── "I'm runner 42" (credential) ───────────▶│ Report job complete
        │── "I'm runner 42" (credential) ───────────▶│ Deregister myself
```

**What the credential provides:**

```
┌────────────────────────────────────────────────────────────────────┐
│  1. IDENTITY    — Proves to GitHub "I am runner 42, not an        │
│                   imposter"                                        │
│                                                                    │
│  2. AUTHORIZATION — GitHub checks "is runner 42 allowed to        │
│                     receive job 789?" (was it assigned to this     │
│                     scale set?)                                    │
│                                                                    │
│  3. SESSION     — Every subsequent API call (logs, status,        │
│                   artifacts, completion) uses this as bearer token │
│                                                                    │
│  4. INTEGRITY   — GitHub can trust that logs/results came from    │
│                   the real runner, not a man-in-the-middle         │
└────────────────────────────────────────────────────────────────────┘

Think of it as: an API key for the runner's ENTIRE conversation
with GitHub, from "hello" to "goodbye"
```

**What happens without any credential?**

```
┌──────────────────────────────────────────────────────────────┐
│  WITHOUT any credential on the pod:                           │
│                                                               │
│  • Pod can't open long-poll connection                        │
│    (GitHub: "who are you? rejected.")                         │
│                                                               │
│  • Pod runs the job... but can't send logs to GitHub          │
│    (GitHub: "who are you? rejected.")                         │
│                                                               │
│  • Pod finishes... but can't report success/failure           │
│    (GitHub: "who are you? rejected.")                         │
│                                                               │
│  • Pod wants to upload artifacts... rejected.                 │
│                                                               │
│  • Job hangs forever as "In Progress" on GitHub UI            │
│    because nobody authenticated is telling GitHub it's done   │
│                                                               │
│  Also:                                                        │
│  • Any random machine could POST fake logs to GitHub          │
│  • Anyone could claim "job succeeded" for your workflow       │
│  • No way to verify that results came from YOUR runner        │
└──────────────────────────────────────────────────────────────┘
```

**Why registration is needed (separate from the credential):**

1. GitHub needs to **know the runner exists** before assigning it a job
2. GitHub needs to **issue a scoped credential** so the runner can make authenticated calls
3. GitHub needs to **track which runner is doing what** (UI, billing, audit logs)

Without registration, GitHub has no way to distinguish your legitimate runner from a random machine on the internet claiming to be one.

**Analogy — phone call with your bank:**

| Step | Without auth | With auth |
|------|-------------|-----------|
| "Transfer $500" | Bank: "Who is this? No." | Bank: "Verified. Done." |
| "What's my balance?" | Bank: "Prove who you are" | Bank: "$1200" |
| "Close my account" | Bank: "Absolutely not" | Bank: "Confirmed" |

The credential isn't just for "calling the bank" (connecting). It's needed for **every action during the call** (the entire session).

### Failure Handling During Registration

```
                    ┌──────────────────┐
                    │ EphemeralRunner  │
                    │ Controller       │
                    └────────┬─────────┘
                             │
                ┌────────────▼────────────┐
                │ Create Runner Pod       │
                └────────────┬────────────┘
                             │
                     ┌───────▼───────┐
                     │ Pod status?   │
                     └───────┬───────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
        ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼─────┐
        │ Running   │ │ Failed    │ │ Pending   │
        │ (success) │ │           │ │ (stuck)   │
        └───────────┘ └─────┬─────┘ └─────┬─────┘
                            │             │
                      ┌─────▼─────┐       │
                      │ Retry     │       │ After 24h, GitHub
                      │ (up to 5x │       │ unassigns the job
                      │  with     │       │
                      │  backoff) │       │
                      └─────┬─────┘       │
                            │             │
                     ┌──────▼──────┐      │
                     │ Still fails │      │
                     └──────┬──────┘      │
                            │             │
                     ┌──────▼─────────────▼──┐
                     │ Mark EphemeralRunner  │
                     │ as failed             │
                     │ GitHub unassigns job  │
                     │ (re-queued or failed) │
                     └───────────────────────┘
```

Key failure behaviors:
- **Pod creation fails**: Controller retries up to 5x with exponential backoff
- **Resource quota exceeded**: Controller handles "status forbidden" and retries
- **JIT token request fails**: Exponential backoff on token generation
- **Runner never connects**: GitHub times out after 24 hours, unassigns the job
- **Listener pod evicted**: Controller restarts it automatically
- **Long-poll session expires**: Listener refreshes the session token

---

## How GitHub Communicates with Pods (It Doesn't — Pods Call Out)

### The Key Insight

GitHub **never initiates** a connection to your pods. All communication is **outbound from your infrastructure**. The pod opens an HTTPS connection to GitHub and holds it open — GitHub responds on that same connection when there's something to say.

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│   COMMON MISCONCEPTION:                                                  │
│                                                                          │
│   GitHub ──────── pushes jobs to ──────────▶ Runner Pod     ✗ WRONG      │
│                                                                          │
│                                                                          │
│   REALITY:                                                               │
│                                                                          │
│   Runner Pod ──── opens HTTPS connection ──▶ GitHub                      │
│              ◀─── GitHub responds on the ─── (same connection)           │
│                   ALREADY-OPEN connection                ✓ CORRECT       │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### Why? Pods Are Behind NAT/Firewalls

```
┌──────────────────────────────────────┐       ┌─────────────────────┐
│  YOUR K8s CLUSTER                    │       │  GITHUB             │
│                                      │       │                     │
│  ┌────────────┐                      │       │  actions.github.com │
│  │ Runner Pod │                      │       │                     │
│  │ 10.0.5.23  │ ← private IP        │       │  Public IP          │
│  └─────┬──────┘   (not routable     │       │                     │
│        │            from internet)   │       │                     │
│  ┌─────▼──────┐                      │       │                     │
│  │ K8s Service│                      │       │                     │
│  │ / NAT      │                      │       │                     │
│  └─────┬──────┘                      │       │                     │
│  ┌─────▼──────┐                      │       │                     │
│  │ Firewall   │  Only OUTBOUND 443 ──┼──────▶│                     │
│  │            │  allowed             │       │                     │
│  └────────────┘                      │       │                     │
│                                      │       │  GitHub has NO way  │
│  No inbound ports open!              │       │  to initiate a      │
│  GitHub can't reach 10.0.5.23        │       │  connection to you  │
└──────────────────────────────────────┘       └─────────────────────┘
```

### The Mechanism: HTTPS Long-Polling

```
Runner Pod                                          GitHub Actions Service
    │                                                        │
    │  ① HTTPS GET /messages                                 │
    │     "Hey GitHub, got anything for me?"                  │
    │────────────────────────────────────────────────────────▶│
    │                                                        │
    │         ② GitHub holds the connection OPEN              │
    │            (doesn't respond yet)                        │
    │            ...                                          │
    │            ... seconds pass ...                         │
    │            ... maybe 30-60 seconds ...                  │
    │                                                        │
    │                                                        │  ← job arrives
    │                                                        │
    │  ③ GitHub responds ON THE SAME CONNECTION              │
    │     {jobId: 123, payload: ...}                          │
    │◀────────────────────────────────────────────────────────│
    │                                                        │
    │  ④ Runner processes job                                │
    │                                                        │
    │  ⑤ HTTPS POST /logs, /timeline, /complete              │
    │     (normal request-response for each)                  │
    │────────────────────────────────────────────────────────▶│
    │                                                        │
    │  ⑥ Back to step ①: open a NEW long-poll               │
    │     (or connection times out → reconnect)              │
    │────────────────────────────────────────────────────────▶│
    │                                                        │
```

### What is Long-Polling vs. Naive Polling?

```
┌─────────────────────────────────────────────────────────────────┐
│  POLLING (naive, wasteful)                                       │
│                                                                  │
│  Client: "Any jobs?" → Server: "No"     (every 5 seconds)       │
│  Client: "Any jobs?" → Server: "No"                             │
│  Client: "Any jobs?" → Server: "No"                             │
│  Client: "Any jobs?" → Server: "No"                             │
│  Client: "Any jobs?" → Server: "Yes! Here's the job"            │
│                                                                  │
│  Problem: thousands of runners × every 5 seconds = API rate     │
│           limits destroyed, massive GitHub server load            │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  LONG-POLLING (what ARC uses)                                    │
│                                                                  │
│  Client: "Any jobs?" → Server: ...holds connection open...       │
│                                  ...waits...                     │
│                                  ...job arrives...               │
│                         Server: "Yes! Here's the job"            │
│                                                                  │
│  ONE request, ONE response. No wasted round trips.               │
│  Near-instant delivery (as fast as a push).                      │
│  No API rate limit issues.                                       │
└─────────────────────────────────────────────────────────────────┘
```

### All Connections Are Outbound from Your Infra

```
YOUR K8s                                         GITHUB (public internet)
────────                                         ────────────────────────

Listener Pod ────── long-poll (HTTPS 443) ──────▶ Actions Service
                    "waiting for job assignments"    (message broker)

Runner Pod ──────── long-poll (HTTPS 443) ──────▶ Actions Service
                    "waiting for my job payload"

Runner Pod ──────── POST (HTTPS 443) ───────────▶ Actions Service
                    "here are my logs"

Runner Pod ──────── POST (HTTPS 443) ───────────▶ Actions Service
                    "step 3 completed"

Runner Pod ──────── PUT (HTTPS 443) ────────────▶ Artifact Service
                    "uploading build artifacts"

Runner Pod ──────── DELETE (HTTPS 443) ─────────▶ Registration Service
                    "I'm done, deregister me"


ALL arrows point →  (outbound from your infra)
ZERO arrows point ← (nothing inbound)
```

### Why This Design?

| Reason | Explanation |
|--------|-------------|
| **Firewall-friendly** | Only need outbound HTTPS (443). No inbound ports, no public IPs for runners |
| **NAT-friendly** | Pods have private IPs (10.x, 172.x). GitHub couldn't reach them even if it wanted to |
| **No webhook infra needed** | Webhooks require a public endpoint + TLS cert + ingress. Long-poll needs nothing |
| **No rate limiting** | One long-lived connection vs. thousands of polling requests per minute |
| **Scales to zero** | When no pods exist, no connections exist. GitHub just holds jobs in queue |
| **Works behind corporate proxies** | Just a normal HTTPS request from the proxy's perspective |

### Compare: Webhooks vs. Long-Poll

```
┌─────────────────────────────────────────┐  ┌────────────────────────────────────────┐
│  WEBHOOK MODEL (NOT what ARC uses)      │  │  LONG-POLL MODEL (what ARC uses)       │
│                                         │  │                                        │
│  GitHub ──POST──▶ your-public-endpoint  │  │  Your pod ──GET──▶ GitHub              │
│                                         │  │           ◀─response── (when ready)    │
│  Requires:                              │  │                                        │
│   • Public DNS name                     │  │  Requires:                             │
│   • Ingress controller                  │  │   • Outbound HTTPS only                │
│   • TLS certificate                     │  │   • Nothing else                       │
│   • Open firewall port                  │  │                                        │
│   • DDoS protection                     │  │                                        │
└─────────────────────────────────────────┘  └────────────────────────────────────────┘
```

This is why ARC works in any environment — air-gapped networks (with a proxy), private clusters, behind NATs — as long as you have outbound HTTPS to `github.com` / `*.actions.githubusercontent.com`.

---

## Summary: Every GitHub API Interaction

| When | Who calls | GitHub API endpoint | Purpose |
|------|-----------|-------------------|---------|
| Setup (once) | Controller | Register scale set | Makes GitHub aware of NTSK pool |
| Setup (once) | Listener | Acquire message session | Opens long-poll channel |
| **Ongoing** | Listener | Long-poll messages | Receives job assignments |
| Per job | Runner pod | Register runner (JIT) | "I exist, give me work" |
| Per job | Runner pod | Get job payload | Fetches steps to execute |
| During job | Runner pod | POST live logs | Streams output to UI |
| During job | Runner pod | POST step timeline | Updates step status in UI |
| During job | Runner pod | Artifacts/cache API | Upload artifacts, save/restore cache |
| Job end | Runner pod | POST job complete | Reports success/failure |
| Job end | Runner pod | DELETE runner | Deregisters itself |
| Job end | Listener | ACK completion | Tells GitHub "I handled it" |

---

## What GitHub Sees vs. What You Control

| GitHub knows | You control |
|---|---|
| Scale set exists (name, labels) | Node size, count, GPU, arch |
| How many runners are idle/busy | Runner image (tools installed) |
| Job queue depth per scale set | Scaling bounds (min/max) |
| Job logs, duration, status | Container mode (dind/k8s/none) |
| Billable minutes (if applicable) | Secrets, volumes, network policy |
| Runner OS/arch (reported by pod) | Which namespace, which cluster |

**GitHub CANNOT** SSH into runners, see the cluster state, or access the volumes/secrets.

**You CANNOT** control job assignment algorithm, modify GitHub's queue priority, or skip runner registration.

The key insight: GitHub treats NTSK scale set as a **black box pool**. It assigns jobs to the pool; NTSK infrastructure decides how to fulfill them. The only contract between the two sides is the runner registration/deregistration API and the job lifecycle messages.

---

## Listener Logging Configuration

The listener pod (`ghalistener`) supports configurable log levels — it is **not** hardcoded to `info`.

### How It Works

1. The **controller's `--log-level` flag** (set in the Helm chart `gha-runner-scale-set-controller`) defaults to `debug`
2. The controller propagates its log level to the listener pod's config JSON via `SetListenerLoggingParameters()`
3. The listener reads `log_level` from its config file and creates a logger supporting: `debug`, `info`, `warn`, `error`

### Configuring Log Level

Set `flags.logLevel` in the controller's Helm values:

```yaml
# charts/gha-runner-scale-set-controller/values.yaml
flags:
  logLevel: "debug"   # valid: "debug", "info", "warn", "error"
  logFormat: "text"   # valid: "text", "json"
```

### Code Path

```
Controller main.go
  → flag.StringVar(&logLevel, "log-level", "debug", ...)
  → SetListenerLoggingParameters(logLevel, logFormat)
      → sets package-level vars: scaleSetListenerLogLevel, scaleSetListenerLogFormat
      → these are written into the listener config JSON when the listener pod is created

Listener cmd/ghalistener/main.go
  → config.Read() parses JSON config (including log_level, log_format)
  → config.Logger() calls logger.New(logLevel, logFormat)
      → creates slog.Logger with the specified level
```

### No Image Rebuild Required

Changing the log level does **not** require rebuilding the Docker image. The Helm values are just passed as command-line args to the existing container at deploy time:

```yaml
# charts/gha-runner-scale-set-controller/templates/deployment.yaml
{{- with .Values.flags.logLevel }}
- "--log-level={{ . }}"
{{- end }}
```

The binary inside the image (`/manager`) already supports all log levels (`debug`, `info`, `warn`, `error`) — it's parsed via `flag.StringVar` at startup (`main.go:160`). You just need a `helm upgrade`:

```bash
helm upgrade <release-name> gha-runner-scale-set-controller \
  --set flags.logLevel=debug
```

Or update your values file and run `helm upgrade -f values.yaml ...`. The controller pod will restart with the new arg, and subsequent listener pods it creates will inherit the new log level in their config JSON.

### Key Files (actions-runner-controller repo)

| File | Role |
|------|------|
| `charts/gha-runner-scale-set-controller/values.yaml` | Helm values with `flags.logLevel` |
| `main.go:160` | Controller's `--log-level` flag definition |
| `controllers/actions.github.com/constants.go:73` | Default: `debug` |
| `controllers/actions.github.com/resourcebuilder.go:54` | `SetListenerLoggingParameters()` |
| `cmd/ghalistener/config/config.go:42` | Listener config struct with `log_level` field |
| `logger/logger.go` | `slog.Logger` factory supporting debug/info/warn/error |

### Default Behavior

The default log level for both the controller and listener is **`debug`** (not `info`). If you're seeing only info-level logs, something in your deployment is explicitly setting `--log-level=info` or the config JSON has `"log_level": "info"`.

---

## CVE-2026-34040: Docker Authorization Plugin Bypass

### Overview

- **Affects**: Docker Engine (via Moby)
- **Issue**: Authorization Plugin Bypass in the API layer

### How it works

Docker's API layer supports authorization plugins that act as policy gatekeepers — they evaluate API requests and decide whether to allow or deny them. This CVE exploits a flaw in how the authorization plugin chain is invoked during API request handling. Under specific conditions, requests slip through **without being evaluated by the plugins at all** — no deny, no alert, just an implicit allow.

### Impact

- An attacker (or misconfigured workload) can perform container operations that should be restricted by policy — pulling images, mounting volumes, running privileged containers
- Runtime security tools that depend on these plugins for enforcement become blind to the activity
- It's a **control plane bypass**, not a container escape — subtle and easy to miss

### Remediation

1. **Patch Docker Engine** to a fixed version
2. **Don't rely solely on runtime enforcement** — build-time security (minimal base images, no unnecessary packages, locked-down configs baked into the image) reduces what an attacker can do even if runtime controls are bypassed
3. **Minimize container attack surface** — fewer tools and capabilities in the image means less to exploit

### Takeaway

Runtime authorization is a last line of defense, not the only one. Defense-in-depth matters for container security.
