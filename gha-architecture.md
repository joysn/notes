# GitHub Actions ARC — Architecture Deep Dive

## 1. Overview & Architecture at a Glance

ARC (Actions Runner Controller) is a Kubernetes operator that provides autoscaled, ephemeral GitHub Actions self-hosted runners. Instead of manually managing VMs, you declare scaling bounds and ARC dynamically creates/destroys runner pods based on workflow demand.

### High-Level Architecture

```
┌───────────────────────────────────────────────┐  ┌──────────────────────────────────────────────┐
│         GITHUB (their infra)                  │  │           YOUR INFRASTRUCTURE (K8s)          │
│                                               │  │                                              │
│  ┌───────────┐  ┌───────────────┐             │  │  ┌────────────┐  ┌──────────┐  ┌───────────┐│
│  │ Actions   │  │ Runner        │             │  │  │ ARC        │  │ Listener │  │ Runner    ││
│  │ Service   │  │ Registration  │             │  │  │ Controller │  │ Pod      │  │ Pod(s)    ││
│  └───────────┘  └───────────────┘             │  │  └────────────┘  └──────────┘  └───────────┘│
│  ┌───────────┐  ┌───────────────┐             │  │                                              │
│  │ Job Queue │  │ GitHub UI /   │             │  │  ┌────────────────────────────────────────┐  │
│  │           │  │ API + Checks  │             │  │  │ Kubernetes API Server                  │  │
│  └───────────┘  └───────────────┘             │  │  └────────────────────────────────────────┘  │
└───────────────────────────────────────────────┘  └──────────────────────────────────────────────┘
```

### What GitHub Sees vs. What You Control

| GitHub knows | You control |
|---|---|
| Scale set exists (name, labels) | Node size, count, GPU, arch |
| How many runners are idle/busy | Runner image (tools installed) |
| Job queue depth per scale set | Scaling bounds (min/max) |
| Job logs, duration, status | Container mode (dind/k8s/none) |
| Billable minutes (if applicable) | Secrets, volumes, network policy |
| Runner OS/arch (reported by pod) | Which namespace, which cluster |

GitHub CANNOT SSH into runners, see cluster state, or access volumes/secrets. You CANNOT control job assignment algorithm, modify GitHub's queue priority, or skip runner registration. GitHub treats your scale set as a **black box pool** — it assigns jobs to the pool; your infrastructure decides how to fulfill them.

### Key Terminology

| Term | Meaning |
|------|---------|
| **Runner Scale Set** | A named, autoscaled pool of runners registered to a repo/org/enterprise |
| **Listener** | A long-polling process that receives job notifications from GitHub |
| **Scaler** | Component inside the listener that patches K8s resources to adjust replica count |
| **JIT Config** | Just-In-Time token — single-use credential for a runner pod to connect to GitHub |
| **EphemeralRunner** | A runner that executes exactly one job, then self-destructs |

---

## 2. Foundational Concepts

### Kubernetes Operators (Brief)

An Operator is a controller + CRD (Custom Resource Definition) + domain logic. It continuously watches custom resources and reconciles actual state toward desired state. Unlike a Deployment (which just keeps N pods alive), an Operator encodes application-specific knowledge: how to register/deregister with external services, handle graceful drain, scale based on external signals.

ARC is an Operator: it watches `AutoscalingRunnerSet` CRDs and orchestrates the full lifecycle — registering with GitHub, polling for jobs, creating runner pods, and cleaning up.

### The Communication Model: Outbound-Only Long-Polling

**All communication is outbound from your infrastructure.** GitHub never initiates connections to your pods.

```
COMMON MISCONCEPTION:
  GitHub ── pushes jobs to ──> Runner Pod          WRONG

REALITY:
  Runner Pod ── opens HTTPS connection ──> GitHub
             <── GitHub responds on the ── (same connection)   CORRECT
```

**Why?** Pods are behind NAT/firewalls with private IPs. GitHub can't reach them. No inbound ports, ingress, or webhooks needed — just outbound HTTPS (443).

**Long-polling vs. naive polling:**

```
POLLING (wasteful):
  Client: "Any jobs?" -> Server: "No"    (every 5 seconds)
  Client: "Any jobs?" -> Server: "No"
  Client: "Any jobs?" -> Server: "Yes!"
  Problem: thousands of runners x every 5 seconds = rate limits destroyed

LONG-POLLING (what ARC uses):
  Client: "Any jobs?" -> Server: ...holds connection open...
                                  ...waits...
                                  ...job arrives...
                         Server: "Yes! Here's the job"
  ONE request, ONE response. Near-instant delivery. No rate limit issues.
```

**Comparison with webhooks:**

| | Webhooks | Long-Poll (ARC) |
|---|---|---|
| Direction | GitHub POSTs to you | You GET from GitHub |
| Requires | Public DNS, ingress, TLS, open port | Outbound HTTPS only |
| Works behind NAT | No | Yes |
| Works in air-gapped (with proxy) | No | Yes |

### CRD Hierarchy

```
AutoscalingRunnerSet   <-- user creates (via Helm chart)
|                         "I want 0-60 runners for org/repo"
|
+-- EphemeralRunnerSet  <-- controller creates
|   |                      "Pod template + current replica count"
|   |
|   +-- EphemeralRunner <-- controller creates (one per job)
|   |                      "State machine for a single runner lifecycle"
|   +-- EphemeralRunner
|   +-- ...
|
+-- AutoscalingListener <-- controller creates (in controller namespace)
                           "Config for the listener pod"
```

| CRD | Key Spec Fields | Key Status Fields |
|-----|----------------|------------------|
| `AutoscalingRunnerSet` | `githubConfigUrl`, `minRunners`, `maxRunners`, `template` (pod spec) | `phase`, `currentRunners` |
| `EphemeralRunnerSet` | `replicas` (set by listener), `patchID`, `ephemeralRunnerSpec` | `currentReplicas`, `pendingEphemeralRunners`, `runningEphemeralRunners` |
| `EphemeralRunner` | `githubConfigUrl`, `runnerScaleSetId`, pod template | `phase`, `runnerId`, `jobId`, `failures` |
| `AutoscalingListener` | `runnerScaleSetId`, `maxRunners`, `minRunners`, `image` | (pod spec holder only) |

### RunnerScaleSet vs AutoscalingRunnerSet vs EphemeralRunnerSet

| | RunnerScaleSet | AutoscalingRunnerSet | EphemeralRunnerSet |
|---|---|---|---|
| **Where** | GitHub's Actions Service (their DB) | K8s API (your cluster) | K8s API (your cluster) |
| **Created by** | Controller calls GitHub API | You (via Helm chart) | Controller (automatically) |
| **Represents** | "GitHub knows this pool exists" | "I want runners with these settings" | "Pod template + current desired count" |
| **Read by** | GitHub (to assign jobs) | AutoscalingRunnerSet controller | EphemeralRunnerSet controller + Listener |
| **Written by** | Controller (register/update/delete) | You (Helm upgrade) | Listener (patches `replicas` + `patchID`) |

### Scale Set vs. Runner Group

- A **runner group** (GitHub concept) is an access-control boundary — "which repos can use these runners"
- A **scale set** (ARC/K8s concept) is a deployment unit — "a pool of pods with specific resources, scaling rules, and container mode"

Multiple scale sets can share one runner group (e.g., `linux-small` with 2 CPU, `linux-gpu` with GPU).

---

## 3. Deployment Architecture

### Two Helm Charts

ARC is deployed via two separate Helm charts:

| Chart | Install frequency | What it deploys |
|-------|-------------------|----------------|
| `gha-runner-scale-set-controller` | Once per cluster | Controller manager pod (the operator) |
| `gha-runner-scale-set` | Once per runner pool | AutoscalingRunnerSet CR (triggers the operator) |

```
helm install arc-controller \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller

helm install my-runners \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set \
  --set githubConfigUrl="https://github.com/org" \
  --set githubConfigSecret="github-secret" \
  --set maxRunners=10
```

The controller chart deploys the operator binary. The runner-set chart creates a CR that the operator watches. This separation means you can have many runner pools (different images, scaling bounds, labels) managed by a single controller.

### Single Image, Two Binaries

```
+-------------------------------------------------------------------------+
|                     SINGLE DOCKER IMAGE                                  |
|           (ghcr.io/actions/gha-runner-scale-set-controller)             |
|                                                                          |
|   /manager                           /ghalistener                        |
|   (Controller Manager)               (Listener)                          |
|   Runs as: controller pod            Runs as: listener pod               |
|   One per cluster                    One per scale set                   |
|   Contains 4 reconcile controllers   Contains message loop + scaler     |
+-------------------------------------------------------------------------+
```

Built from a single Dockerfile:
```dockerfile
# Dockerfile (simplified)
RUN go build -o /out/manager main.go
RUN go build -o /out/ghalistener ./cmd/ghalistener
ENTRYPOINT ["/manager"]
```

### Runtime Layout (Namespaces)

```
+-------------------------------------------------------------------------+
|  YOUR K8s CLUSTER                                                        |
|                                                                          |
|  +--------------------------------------------------------------+       |
|  |  Controller Namespace (e.g., "arc-systems")                   |       |
|  |                                                               |       |
|  |  [Controller Manager Pod]    [Listener Pod A]   [Listener B]  |       |
|  |   /manager binary             /ghalistener       /ghalistener  |       |
|  |   4 reconcile loops           for scale-set-1    for set-2     |       |
|  |                                                               |       |
|  |  [ServiceAccount A] [Config Secret A] [Role/RoleBinding...]   |       |
|  +--------------------------------------------------------------+       |
|                                                                          |
|  +--------------------------------------------------------------+       |
|  |  Runner Namespace (e.g., "arc-runners")                       |       |
|  |                                                               |       |
|  |  [AutoscalingRunnerSet]  [EphemeralRunnerSet]                 |       |
|  |  [EphemeralRunner 1]     [EphemeralRunner 2]                  |       |
|  |  [Runner Pod 1]          [Runner Pod 2]    [JIT Secrets...]   |       |
|  +--------------------------------------------------------------+       |
+-------------------------------------------------------------------------+
```

The controller and listener pods run in one namespace; runner CRs and pods run in another. This separation enables:
- Tighter RBAC (runners can't see controller secrets)
- Multiple runner namespaces managed by one controller
- Independent lifecycle management

### Container Modes

The `containerMode` setting controls how workflow steps execute inside the runner pod:

| Mode | How it works | Use case |
|------|-------------|----------|
| **none** (default) | Steps run as processes inside the runner container | Simple jobs, no Docker needed |
| **dind** (Docker-in-Docker) | A sidecar Docker daemon container; steps can `docker build/run` | Jobs that build/push Docker images |
| **kubernetes** | Steps run as separate K8s pods via container hooks | Full pod isolation per step, custom resource limits per step |

With `dind`, the runner pod gets a privileged sidecar running dockerd. With `kubernetes`, the runner uses `ACTIONS_RUNNER_CONTAINER_HOOKS` to create K8s pods for each workflow step (linked via `runner-pod: <name>` labels, cleaned up by the EphemeralRunner controller).

### Configuration Flow

```
Helm values.yaml
  --> Controller Deployment args (--log-level, --update-strategy, ...)
  --> AutoscalingRunnerSet CR (githubConfigUrl, min/maxRunners, template)
  --> AutoscalingListener CR (derived from ARS)
  --> Listener Config Secret (JSON with all params)
  --> Listener Pod (reads /etc/gha-listener/config.json)
  --> Scaler (uses config for K8s patches)
```

### Scaling Configurations

| Config | Behavior |
|--------|----------|
| Both omitted | 0 to MaxInt32 (unbounded, scales to zero when idle) |
| `minRunners: 5` | Always 5 warm runners ready, scales up from there |
| `maxRunners: 30` | Never exceed 30 concurrent runners |
| Both set to `0` | Drains — no new runners created |

Formula: `desired = min(minRunners + assignedJobs, maxRunners)`

---

## 4. Security Model

### Authentication: GitHub App vs PAT

ARC authenticates to GitHub using one of two methods:

| | GitHub App | Personal Access Token (PAT) |
|---|---|---|
| **Scope** | Per-installation (org or repo) | Per-user |
| **Rotation** | Auto (JWT → installation token, 1hr TTL) | Manual (classic) or auto (fine-grained, max 1yr) |
| **Permissions** | Granular (select only what's needed) | Broad token scopes |
| **Rate limits** | Higher (per-app installation) | Shared with user |
| **Revocation** | Org admin can revoke installation | Token owner revokes |
| **Best for** | Production, org-wide | Personal repos, quick setup |

**GitHub App flow:**
```
Controller has: App ID + Private Key (PEM)
  1. Signs JWT (RS256, 10min TTL)
  2. Exchanges JWT for Installation Token (1hr TTL)
  3. Uses Installation Token for all Actions Service API calls
  4. Auto-refreshes before expiry
```

**PAT flow:**
```
Controller has: Token string
  1. Uses token directly in Authorization header
  2. No refresh mechanism — token must be rotated externally
```

The authentication credential (App or PAT) is stored in a K8s Secret referenced by `githubConfigSecret` in the AutoscalingRunnerSet spec. The controller reads this secret to authenticate all GitHub API calls: registering scale sets, creating sessions, generating JIT configs.

### JIT (Just-In-Time) Runner Tokens

Every runner pod needs credentials to connect to GitHub. ARC uses **JIT configuration** — single-use, short-lived tokens generated per runner.

**Why JIT exists (vs. pre-registered runners):**

```
WITHOUT JIT (traditional self-hosted runners):
  1. Admin manually registers runner → gets a long-lived token
  2. Token stored on disk → risk if compromised
  3. Runner reuses token across jobs → lateral movement risk
  4. Must manually deregister on teardown

WITH JIT (ARC ephemeral runners):
  1. Controller calls GitHub API: "Generate JIT config for runner X"
  2. GitHub returns single-use encoded config (contains token + registration)
  3. Config stored as K8s Secret, mounted into pod
  4. Runner uses it once → pod dies → token is invalid
  5. No manual registration/deregistration needed
```

**JIT config lifecycle:**
```
EphemeralRunner Controller                    GitHub
        |                                       |
        |-- GenerateJitRunnerConfig(name) ----->|
        |                                       |-- Creates runner registration
        |<---- {encodedJITConfig, runnerRef} ---|    (ID assigned, single-use)
        |                                       |
        |-- Create K8s Secret (jit-config) ---->| (stored in runner namespace)
        |-- Create Pod (mounts secret) -------->|
        |                                       |
        [Pod starts]                            |
        |   Runner binary reads JIT config      |
        |   Runner connects to GitHub --------->|-- Validates token
        |                                       |-- Assigns job
        [Job runs]                              |
        [Pod terminates]                        |
        |                                       |-- Token now invalid
        |-- Delete Secret ----------------------|
        |-- Remove runner registration -------->|
```

**Analogy:** JIT config is like a hotel key card — it's programmed for one guest, one room, one stay. When you check out, the card is deactivated.

### RBAC & Cross-Namespace Permissions

ARC uses a cross-namespace RBAC model. The listener pod runs in the **controller namespace** but needs to modify resources in the **runner namespace**.

**Resources created by the AutoscalingListener controller:**

| Resource | Namespace | Purpose |
|----------|-----------|---------|
| ServiceAccount | Controller ns | Identity for the listener pod |
| Role | Runner ns | Permissions to patch ERS + ER resources |
| RoleBinding | Runner ns | Binds Role → ServiceAccount (cross-ns) |
| Config Secret | Controller ns | Listener configuration JSON |
| Listener Pod | Controller ns | Runs the /ghalistener binary |

**Role permissions (exact rules):**

```yaml
# The listener can patch ONE specific EphemeralRunnerSet (by name)
- apiGroups: ["actions.github.com"]
  resources: ["ephemeralrunnersets"]
  resourceNames: ["<specific-ers-name>"]
  verbs: ["patch"]

# The listener can patch status of EphemeralRunners (for job started/completed)
- apiGroups: ["actions.github.com"]
  resources: ["ephemeralrunners", "ephemeralrunners/status"]
  verbs: ["patch"]
```

This is **least-privilege by design**: the listener can only modify the one ERS it manages, not others in the same namespace.

**Cross-namespace binding:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  namespace: arc-runners          # <-- Role lives here
subjects:
- kind: ServiceAccount
  name: <listener-sa>
  namespace: arc-systems           # <-- SA lives here (different namespace!)
roleRef:
  kind: Role
  name: <listener-role>
```

**Cross-namespace watch mechanism:**

The controller needs to watch resources across namespaces. It uses label-based watches:
```go
// Labels stamped on cross-namespace resources
"auto-scaling-listener-namespace": "<controller-ns>"
"auto-scaling-listener-name":      "<listener-name>"
```

The controller's informer filters on these labels, enabling it to watch Role/RoleBinding objects in runner namespaces without cluster-wide permissions.

### Credential Isolation Design

```
┌─────────────────────────────────────┐
│ Controller Namespace                 │
│                                      │
│  [GitHub App Secret]                 │  ← Only controller pod reads this
│  [Listener Config Secrets]           │  ← One per scale set
│  [Proxy/TLS Secrets]                 │  ← Optional
│                                      │
│  Controller pod: full GitHub API     │
│  Listener pod: message queue only    │
│                                      │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│ Runner Namespace                     │
│                                      │
│  [JIT Config Secrets]                │  ← One per runner, single-use
│  [Runner Pods]                       │  ← Cannot see controller secrets
│                                      │
│  Runner pod: connects to GitHub      │
│  with JIT token (one job only)       │
│                                      │
└─────────────────────────────────────┘
```

**Key isolation properties:**
- Runner pods cannot access the GitHub App private key
- Runner pods cannot see other runners' JIT tokens
- Listener pods cannot create/delete pods (only patch ERS replica counts)
- A compromised runner can only affect its single assigned job

### Naming Conventions

ARC uses deterministic naming with hash suffixes to avoid collisions:

| Resource | Pattern | Example |
|----------|---------|---------|
| EphemeralRunnerSet | `<ars-name>-<hash8>` | `my-runners-a1b2c3d4` |
| Listener Pod | `<ars-name>-<hash8>-listener` | `my-runners-a1b2c3d4-listener` |
| ServiceAccount | `<ars-name>-<hash8>-listener` | `my-runners-a1b2c3d4-listener` |
| Role | `<ars-name>-<hash8>-listener` | `my-runners-a1b2c3d4-listener` |
| Config Secret | `<ars-name>-<hash8>-listener-config` | `my-runners-a1b2c3d4-listener-config` |
| EphemeralRunner | `<ers-name>-<random5>` | `my-runners-a1b2c3d4-xk9f2` |
| JIT Secret | `<er-name>-jitconfig` | `my-runners-a1b2c3d4-xk9f2-jitconfig` |

The `<hash8>` is derived from the AutoscalingRunnerSet UID, ensuring uniqueness even if names collide across namespaces.

---

## 5. End-to-End Job Lifecycle

This section traces a single workflow job from `git push` to completion. Four phases, four systems.

### Phase 1: Job Queued (GitHub Side)

```
Developer pushes code
       |
       v
GitHub evaluates workflow YAML
       |
       v
Job created with runs-on labels (e.g., "self-hosted", "linux", "my-scale-set")
       |
       v
Actions Service matches labels → finds your RunnerScaleSet
       |
       v
Job enters queue for that scale set
       |
       v
Actions Service sends message on long-poll connection
```

At this point, GitHub has:
- Created a job with a unique `runnerRequestId`
- Determined which scale set should handle it
- Queued a `JobAvailable` message for the listener's next long-poll response

### Phase 2: Scaling Decision (Listener + Scaler)

```
┌─────────────────────────────────────────────────────────────────────┐
│  LISTENER POD                                                        │
│                                                                      │
│  Message Loop (listener.Run)                                         │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ 1. GetMessage(lastMessageID, maxCapacity)                    │    │
│  │    → Long-poll to GitHub (blocks until message or timeout)   │    │
│  │                                                              │    │
│  │ 2. Response contains:                                        │    │
│  │    - Statistics (assigned, running, idle counts)              │    │
│  │    - JobAvailable messages (new jobs to claim)                │    │
│  │    - JobStarted messages (runners picked up work)            │    │
│  │    - JobCompleted messages (jobs finished)                    │    │
│  │                                                              │    │
│  │ 3. DeleteMessage(messageID) — ACK to GitHub                  │    │
│  │                                                              │    │
│  │ 4. AcquireJobs(requestIDs) — claim available jobs            │    │
│  │    (prevents other scale sets from taking them)              │    │
│  │                                                              │    │
│  │ 5. HandleJobStarted / HandleJobCompleted                     │    │
│  │    (update EphemeralRunner status annotations)               │    │
│  │                                                              │    │
│  │ 6. HandleDesiredRunnerCount(totalAssignedJobs)               │    │
│  │    → Scaler calculates target and patches K8s               │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                      │
│  Scaler                                                              │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │ target = min(minRunners + assignedJobs, maxRunners)          │    │
│  │                                                              │    │
│  │ if target != currentCount || !dirty:                         │    │
│  │   PATCH EphemeralRunnerSet {                                 │    │
│  │     spec.replicas = target                                   │    │
│  │     spec.patchID = nextSequence()                            │    │
│  │   }                                                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

**Key details:**
- `maxCapacity` is sent as an HTTP header (`X-ScaleSetMaxCapacity`) — tells GitHub how many jobs this set can currently accept
- `AcquireJobs` is a claim/lock — once acquired, the job is committed to this scale set
- The scaler patches the ERS in the runner namespace using the cross-namespace ServiceAccount

### Phase 3: Runner Pod Creation (K8s Controllers)

```
EphemeralRunnerSet Controller                  EphemeralRunner Controller
         |                                              |
         |  Reconcile triggered by replica patch        |
         |                                              |
    ┌────┴────┐                                         |
    │ Compare │                                         |
    │ desired │  desired=5, current=3                   |
    │ vs      │  → need 2 more                         |
    │ actual  │                                         |
    └────┬────┘                                         |
         |                                              |
    Create EphemeralRunner CRs (2x)                     |
         |─────────────────────────────────────────────>|
         |                                              |
         |                              ┌───────────────┴──────────────┐
         |                              │ For each new EphemeralRunner: │
         |                              │                               │
         |                              │ 1. Set phase = Pending        │
         |                              │ 2. Call GenerateJitRunnerConfig│
         |                              │    → GitHub returns JIT token │
         |                              │ 3. Create K8s Secret          │
         |                              │    (mount JIT config)         │
         |                              │ 4. Create Pod                 │
         |                              │    (uses runner template)     │
         |                              │ 5. Set phase = Running        │
         |                              │    (once pod is Running)      │
         |                              └───────────────┬──────────────┘
         |                                              |
         |                                              v
         |                              [Runner Pod starts]
         |                              [Runner binary reads JIT config]
         |                              [Runner connects to GitHub]
         |                              [GitHub assigns queued job]
```

### Phase 4: Job Execution & Cleanup

```
Runner Pod                          GitHub                    EphemeralRunner Controller
    |                                  |                              |
    |── "I'm ready" ─────────────────>|                              |
    |                                  |── Assigns job                |
    |<── Job payload ─────────────────|                              |
    |                                  |                              |
    [Executes workflow steps]          |                              |
    |                                  |                              |
    |── Logs streaming ───────────────>|                              |
    |                                  |                              |
    [Job completes]                    |                              |
    |── "Job done, result=success" ──>|                              |
    |                                  |── Sends JobCompleted msg     |
    [Runner process exits (code 0)]   |     to listener              |
    [Pod terminates]                   |                              |
    |                                  |                              |
    |                                  |                    ┌─────────┴──────────┐
    |                                  |                    │ Pod terminated:     │
    |                                  |                    │ 1. Check exit code  │
    |                                  |                    │    (0 = success)    │
    |                                  |                    │ 2. Set phase =      │
    |                                  |                    │    Succeeded        │
    |                                  |                    │ 3. Remove runner    │
    |                                  |                    │    from GitHub      │
    |                                  |                    │ 4. Delete JIT secret│
    |                                  |                    │ 5. Delete pod       │
    |                                  |                    │ 6. ERS controller   │
    |                                  |                    │    sees done runner,│
    |                                  |                    │    adjusts count    │
    |                                  |                    └────────────────────┘
```

### Complete Timeline (Wall-Clock)

| Event | Typical Latency | Bottleneck |
|-------|----------------|------------|
| Push → Job queued | < 1s | GitHub processing |
| Job queued → Listener notified | < 1s | Long-poll response |
| Listener → ERS patched | < 100ms | K8s API call |
| ERS patched → EphemeralRunner created | < 1s | Controller reconcile |
| ER created → JIT config generated | 1-3s | GitHub API call |
| JIT generated → Pod scheduled | 1-30s | K8s scheduler (node availability) |
| Pod scheduled → Runner connected | 5-15s | Image pull + runner startup |
| Runner connected → Job starts | < 1s | GitHub assignment |
| **Total: push → job running** | **~10-50s** | **Dominated by pod scheduling + image pull** |

---

## 6. Scaling Engine Deep Dive

### The Message Loop

The listener's core is an infinite loop that long-polls GitHub for messages:

```go
// Simplified from listener/listener.go
func (l *Listener) Run(ctx context.Context, scaler Scaler) error {
    // Bootstrap: use initial session statistics
    initialStats := l.client.Session().Statistics
    scaler.HandleDesiredRunnerCount(ctx, initialStats.TotalAssignedJobs)

    var lastMessageID int
    for {
        msg, err := l.client.GetMessage(ctx, lastMessageID, l.maxRunners)
        if msg == nil {
            // Timeout/no message — re-assert current state
            scaler.HandleDesiredRunnerCount(ctx, l.latestStatistics.TotalAssignedJobs)
            continue
        }

        lastMessageID = msg.MessageID
        l.handleMessage(ctx, scaler, msg)
    }
}
```

**Message handling order matters:**
1. Store statistics (latest truth from GitHub)
2. Delete message (ACK — prevents redelivery)
3. Acquire available jobs (claim them before scaling)
4. Handle job started/completed (update runner CRs)
5. Handle desired runner count (scale decision)

### Statistics: GitHub's View of the World

Every message includes a `RunnerScaleSetStatistic` snapshot:

```
┌─────────────────────────────────────────────────────┐
│  RunnerScaleSetStatistic                             │
│                                                      │
│  TotalAvailableJobs:     3  ← In queue, unclaimed   │
│  TotalAcquiredJobs:      2  ← Claimed, not assigned │
│  TotalAssignedJobs:      5  ← Assigned to a runner  │
│  TotalRunningJobs:       4  ← Actually executing    │
│  TotalRegisteredRunners: 8  ← Known to GitHub       │
│  TotalBusyRunners:       4  ← Running a job         │
│  TotalIdleRunners:       4  ← Registered, waiting   │
└─────────────────────────────────────────────────────┘
```

The scaler uses `TotalAssignedJobs` as input — this represents the real demand that needs runners.

### The Scaling Formula

```
targetRunners = min(minRunners + totalAssignedJobs, maxRunners)
```

**Examples:**

| minRunners | maxRunners | assignedJobs | Target | Explanation |
|-----------|-----------|-------------|--------|-------------|
| 0 | 10 | 0 | 0 | No demand, scale to zero |
| 0 | 10 | 3 | 3 | Scale to match demand |
| 0 | 10 | 15 | 10 | Capped at max |
| 5 | 10 | 0 | 5 | Warm pool maintained |
| 5 | 10 | 3 | 8 | Warm pool + demand |
| 5 | 10 | 7 | 10 | Capped at max |

### The PatchID Mechanism

The scaler doesn't just write `replicas = N` — it includes a **patchID** for deduplication:

```
Problem without patchID:
  1. Listener patches ERS: replicas=5
  2. ERS controller reconciles, creates 5 runners
  3. Network glitch: listener doesn't see ACK
  4. Listener retries: replicas=5
  5. ERS controller sees same value... but is it a new request?
  
  Without deduplication: controller might create 5 MORE runners

Solution with patchID:
  1. Listener patches ERS: replicas=5, patchID=7
  2. ERS controller reconciles, stores patchID=7
  3. Listener retries: replicas=5, patchID=7
  4. ERS controller: "patchID 7? Already processed. Skip."
```

**PatchID rules:**

| Condition | PatchID Value | Meaning |
|-----------|--------------|---------|
| Normal scale (count changed) | Monotonically increasing (1, 2, 3...) | "New desired state" |
| Identical count, state is dirty | Next sequence number | "Still need this many" |
| Identical count, state is clean, at minRunners | 0 | "Force re-reconcile" (state sync) |

**The "dirty" flag:** After a scale event, the state is "dirty" until the ERS controller has processed it (runners are actually created/deleted). While dirty, the scaler always sends a new patchID even if the count hasn't changed — this ensures the controller processes the request.

**PatchID = 0 ("force state"):** When the system is idle (at minRunners, nothing happening), the scaler sends patchID=0. The ERS controller always processes patchID=0 patches, making it a heartbeat/sync mechanism.

### ERS Controller: Processing Scale Requests

The EphemeralRunnerSet controller receives the replica patch and reconciles:

```
Reconcile triggered (ERS spec changed)
         |
         v
  ┌──────────────────────┐
  │ Read spec.patchID    │
  │ Read latest patchID  │
  │ from annotations     │
  └──────────┬───────────┘
             |
   ┌─────────┴─────────┐
   │ spec.patchID != 0  │──── No ────> Process (force state)
   │ AND                │
   │ spec.patchID ==    │──── Yes ───> Skip (already processed)
   │ latestPatchID      │
   └─────────┬──────────┘
             | (new patchID)
             v
  ┌──────────────────────┐
  │ Classify runners:    │
  │  - pending (no pod)  │
  │  - running (has pod) │
  │  - failed (retrying) │
  │  - done (terminal)   │
  └──────────┬───────────┘
             |
             v
  scaleTotal = pending + running + failed
             |
   ┌─────────┴─────────────────┐
   │ scaleTotal < spec.replicas │──── Scale UP
   │ scaleTotal > spec.replicas │──── Scale DOWN
   │ scaleTotal == spec.replicas│──── No change
   └───────────────────────────┘
```

**Scale UP:** Create new EphemeralRunner CRs (each stamped with the current patchID annotation)

**Scale DOWN:** 
1. Select runners to remove (oldest first)
2. Only remove runners that are registered (`RunnerID > 0`) AND have no assigned job
3. Call GitHub API: `RemoveRunner(runnerID)` — deregisters from GitHub
4. Delete the EphemeralRunner CR
5. If no suitable candidates (all runners are busy), scale-down is deferred

### MaxCapacity Header

The `X-ScaleSetMaxCapacity` header sent with each long-poll tells GitHub how many MORE jobs this scale set can accept:

```
maxCapacity = maxRunners (from config)
```

GitHub uses this to avoid over-assigning jobs to a scale set that's nearly full. If maxCapacity is 0, GitHub won't send new `JobAvailable` messages to this set.

### Metrics Interface

The listener supports pluggable metrics via the `MetricsRecorder` interface:

```go
type MetricsRecorder interface {
    RecordStatistics(statistics *scaleset.RunnerScaleSetStatistic)
    RecordJobStarted(msg *scaleset.JobStarted)
    RecordJobCompleted(msg *scaleset.JobCompleted)
    RecordDesiredRunners(count int)
}
```

These hooks fire at each scaling decision point, enabling custom Prometheus/OpenTelemetry exporters without modifying the listener core.

---

## 7. EphemeralRunner State Machine

Each EphemeralRunner CR is a state machine managed by the EphemeralRunner controller. It tracks the full lifecycle of a single runner — from creation through job execution to cleanup.

### Phases

```
                    ┌─────────┐
                    │ Pending │ ← Initial state (JIT config + pod creation)
                    └────┬────┘
                         │ Pod enters Running state
                         v
                    ┌─────────┐
                    │ Running │ ← Runner connected to GitHub, executing job
                    └────┬────┘
                         │ Pod terminates
            ┌────────────┼────────────┐
            │            │            │
            v            v            v
      ┌───────────┐ ┌────────┐ ┌──────────┐
      │ Succeeded │ │ Failed │ │ Outdated │
      └───────────┘ └────────┘ └──────────┘
       (exit 0)     (retryable) (exit 7, rolling update)
```

| Phase | Meaning | Terminal? |
|-------|---------|-----------|
| **Pending** | JIT config being generated, pod being created | No |
| **Running** | Pod is running, runner connected to GitHub | No |
| **Succeeded** | Job completed successfully (exit code 0) | Yes |
| **Failed** | Pod failed after max retries (5 failures) | Yes |
| **Outdated** | Runner image/config was updated (exit code 7) | Yes |

### The Reconcile Loop

```go
// Simplified decision tree for each reconcile
func Reconcile(er *EphemeralRunner) {
    if er.IsDone() {
        cleanUpResources()  // delete pod, secret, deregister
        return
    }

    pod := getPod(er)

    if pod == nil {
        if shouldCreatePod(er) {
            generateJitConfig()
            createSecret()
            createPod()
        }
        return
    }

    switch pod.Status.Phase {
    case Running:
        er.Status.Phase = Running
        updateRunnerID()

    case Succeeded:
        er.Status.Phase = Succeeded

    case Failed:
        handlePodFailure(er, pod)
    }
}
```

### Pod Failure Handling & Exit Codes

When a pod terminates, the controller inspects the exit code of the runner container:

| Exit Code | Meaning | Action |
|-----------|---------|--------|
| 0 | Job completed successfully | Phase → Succeeded |
| 7 | Runner binary is outdated (rolling update signal) | Phase → Outdated |
| Other (1, 137, etc.) | Crash, OOM, infrastructure failure | Retry (up to 5x) |

**Exit code 7 special case:** GitHub's runner binary returns exit code 7 when it detects that a newer version exists. ARC interprets this as "this runner's image is stale" — it marks the EphemeralRunner as Outdated rather than Failed, which signals the rolling update system.

### Retry Logic

Failed pods are retried with exponential backoff:

```
Attempt 1: immediate (0s delay)
Attempt 2: 5s delay
Attempt 3: 10s delay
Attempt 4: 20s delay
Attempt 5: 40s delay
Attempt 6: GIVE UP → Phase = Failed
```

**Implementation:** The `Status.Failures` field is a `map[string]metav1.Time` keyed by pod UID. Each failed pod's UID is recorded with a timestamp. When `len(Failures) >= 5`, the runner is terminal.

```
┌──────────────────────────────────────────────────────────┐
│ Retry Decision Tree                                       │
│                                                           │
│  Pod terminated with non-zero, non-7 exit code            │
│       |                                                   │
│       v                                                   │
│  len(failures) < 5?                                       │
│       |                                                   │
│    Yes |              No                                  │
│       |               |                                   │
│       v               v                                   │
│  Record failure    Phase = Failed                         │
│  Delete pod        (terminal, stop retrying)              │
│  Requeue with                                             │
│  backoff delay                                            │
│       |                                                   │
│       v                                                   │
│  Next reconcile:                                          │
│  pod == nil, shouldCreate?                                │
│       |                                                   │
│       v                                                   │
│  Check backoff:                                           │
│  time.Since(lastFailure) > backoffDuration[len(failures)]?│
│       |                                                   │
│    Yes → create new pod                                   │
│    No  → requeue after remaining duration                 │
└──────────────────────────────────────────────────────────┘
```

### JIT Config Generation & RunnerExistsError

When creating a new runner, the controller calls GitHub to generate a JIT config. This can fail:

```
GenerateJitRunnerConfig(name, workFolder)
       |
       v
  ┌──────────────┐
  │ Success?     │
  └──────┬───────┘
    Yes  │         No
         │          |
         v          v
  Create secret   ┌─────────────────────────────┐
  + pod           │ Error type?                  │
                  │                              │
                  │ RunnerExistsError:           │
                  │   Runner with same name      │
                  │   already registered.        │
                  │                              │
                  │   Is it ours? (same scale set│
                  │   ID + matches our runner?)  │
                  │     Yes → get existing runner│
                  │           use its config     │
                  │     No  → fatal error        │
                  │           (name collision)   │
                  │                              │
                  │ Other error:                 │
                  │   Record as failure, retry   │
                  └─────────────────────────────┘
```

### The deleteEphemeralRunnerOrPod Decision

When cleaning up a failed runner, the controller decides whether to delete the entire EphemeralRunner or just the pod:

```
Runner has failed, needs cleanup
       |
       v
  HasJob() ? (Status.JobID != "")
       |
    Yes |           No
       |            |
       v            v
  Delete entire    Delete pod only
  EphemeralRunner  (allows retry —
  (job was         new pod will be
  assigned, can't  created on next
  retry — another  reconcile)
  runner needed)
```

**Why this distinction matters:** If a job was already assigned to this runner, GitHub won't reassign it to the same EphemeralRunner. The only recovery is to delete the ER entirely, which lets the ERS controller create a fresh one that can get a new job assignment.

### Finalizers

Each EphemeralRunner has two finalizers that ensure clean shutdown:

| Finalizer | Purpose | Cleanup Actions |
|-----------|---------|-----------------|
| `ephemeralrunner.actions.github.com/finalizer` | Resource cleanup | Delete pod, delete JIT secret, delete work pods (kubernetes mode) |
| `ephemeralrunner.actions.github.com/runner-registration-finalizer` | GitHub deregistration | Call RemoveRunner API to deregister from GitHub |

**Order matters:** Registration finalizer runs first (deregister from GitHub while pod may still be draining), then resource finalizer (delete K8s objects).

**The "job still running" edge case:** If the controller tries to deregister a runner that's actively executing a job, GitHub returns `JobStillRunningError`. The controller backs off and retries — it won't force-delete a runner mid-job.

---

## 8. Rolling Updates

When you change the runner configuration (image, template, env vars, etc.) via `helm upgrade`, ARC performs a rolling update. This section explains how changes are detected, how old runners drain, and how new ones take over.

### Change Detection via Hashing

The controller uses content hashing to detect changes:

```
AutoscalingRunnerSet spec
       |
       v
  RunnerSetSpecHash()  ← hashes: githubConfigUrl, secret, runnerGroup,
       |                   scaleSetName, proxy, TLS, template
       v
  Compare with annotation on latest EphemeralRunnerSet:
    annotations["runner-spec-hash"]
       |
  ┌────┴────┐
  │ Match?  │
  └────┬────┘
   Yes │        No
       │         |
       v         v
  No change    Rolling update needed!
  (normal      (create new ERS, drain old)
   scaling)
```

**Three hash functions serve different purposes:**

| Function | Hashes | Used to detect |
|----------|--------|----------------|
| `RunnerSetSpecHash()` | Runner-affecting fields (template, config, proxy) | Need new ERS (runner pods change) |
| `ListenerSpecHash()` | Full ARS spec | Need to restart listener (any config change) |
| `Hash()` | Entire ARS spec + labels | Need to update GitHub RunnerScaleSet |

### Update Strategies

The `--update-strategy` controller flag (or Helm value) determines how old runners drain:

#### Immediate Strategy (default)

```
Time ──────────────────────────────────────────────────>

  helm upgrade (image changed)
       |
       v
  [ARS Controller detects hash mismatch]
       |
       ├── Create new ERS (v2) with replicas=0
       ├── Mark old ERS (v1) as "outdated"
       ├── Delete old listener pod
       ├── Create new listener (points to v2 ERS)
       |
       v
  [New listener starts]
       ├── Receives jobs → scales v2 ERS
       |
  [Old v1 runners]
       ├── Running jobs: allowed to finish
       ├── Idle runners: immediately terminated
       ├── New jobs: NOT assigned to v1
       |
  [Eventually: all v1 runners done]
       └── Delete v1 ERS + cleanup
```

**Key property:** New pods start immediately on the new config. Old pods with active jobs are allowed to finish (not killed). Idle old pods are terminated right away.

#### Eventual Strategy

```
Time ──────────────────────────────────────────────────>

  helm upgrade (image changed)
       |
       v
  [ARS Controller detects hash mismatch]
       |
       v
  [Check: any running or pending runners on old ERS?]
       |
    Yes |
       v
  WAIT. Do not create new ERS yet.
  Old runners continue receiving AND finishing jobs.
       |
  [Eventually: all old runners complete]
       |
       v
  NOW create new ERS (v2)
  Delete old ERS (v1)
  Create new listener
```

**Key property:** No new ERS is created until the old one is fully drained. This means:
- During drain, the system continues using old runners for new jobs
- Zero "wasted" runner capacity (no overlap period)
- Slower rollout (must wait for all jobs to complete)

**Decision function:**
```go
func drainingJobs(strategy, oldERS) bool {
    if strategy != "eventual" {
        return false  // immediate: never wait
    }
    running := oldERS.Status.RunningEphemeralRunners
    pending := oldERS.Status.PendingEphemeralRunners
    return (running + pending) > 0  // wait until fully drained
}
```

### The Rolling Update Sequence (Immediate)

Detailed step-by-step:

```
1. User runs: helm upgrade --set template.spec.containers[0].image=new-image

2. Helm updates AutoscalingRunnerSet CR
   (K8s API server stores new spec)

3. ARS Controller reconciles:
   a. Computes RunnerSetSpecHash() of new spec
   b. Finds latest ERS, reads its "runner-spec-hash" annotation
   c. Hashes don't match → rolling update

4. ARS Controller creates new ERS (v2):
   - replicas: 0
   - annotations: {"runner-spec-hash": "<new-hash>"}
   - spec: new pod template

5. ARS Controller marks old ERS (v1):
   - Sets phase to "Outdated" (if immediate strategy)

6. ARS Controller deletes old listener pod:
   - Listener was configured to patch v1 ERS
   - New listener will patch v2 ERS

7. ARS Controller creates new AutoscalingListener:
   - Points to v2 ERS name in its config
   - RBAC role updated to allow patching v2 ERS

8. AutoscalingListener Controller reconciles:
   - Creates ServiceAccount, Role, RoleBinding, Config Secret
   - Creates new listener pod

9. New listener starts:
   - Creates session with GitHub (RunnerScaleSet still exists)
   - Receives statistics → scales v2 ERS as needed
   - New runner pods use new image

10. Old ERS (v1) drains:
    - ERS controller sees phase=Outdated
    - Does NOT create new runners
    - Existing runners finish their jobs → phase=Succeeded
    - As runners complete, they're cleaned up normally

11. ARS Controller sees v1 ERS is fully drained:
    - All EphemeralRunners in terminal state
    - Deletes v1 ERS
    - Cleanup complete
```

### Multiple Pending Updates

If you run `helm upgrade` twice before the first update completes:

```
ERS v1 (original) ── outdated, draining
ERS v2 (first update) ── outdated, draining (was active briefly)
ERS v3 (second update) ── ACTIVE (listener points here)
```

The ARS controller sorts EphemeralRunnerSets by creation timestamp (newest first). Only the newest is "active" — all others are treated as outdated and drained.

### What Triggers vs. Doesn't Trigger a Rolling Update

| Change | Triggers Rolling Update? | Why |
|--------|------------------------|-----|
| Runner image | Yes | Pod template changed |
| Runner env vars | Yes | Pod template changed |
| Volume mounts | Yes | Pod template changed |
| minRunners/maxRunners | No | Scaling config only (listener handles it) |
| GitHub config URL | Yes | Different repo/org target |
| GitHub secret | Yes | Different credentials |
| Runner group | Yes | Different runner group assignment |
| Proxy/TLS config | Yes | Connectivity changes |
| Controller image | No | Controller pod managed by its own Deployment |

---

## 9. Operations & Observability

### Logging Architecture

ARC components emit structured logs (JSON or text):

| Component | Log Source | Key Log Fields |
|-----------|-----------|----------------|
| Controller Manager | `/manager` pod | `controller`, `reconcileID`, `namespace`, `name` |
| Listener | `/ghalistener` pod | `scaleSetID`, `messageID`, `assignedJobs` |
| Runner | Runner pod | Job logs (streamed to GitHub, not stored locally) |

**Useful controller log lines to watch:**

```
# Scaling event
"Scaling runner set" controller="EphemeralRunnerSet" replicas=5 patchID=12

# Runner lifecycle
"Creating ephemeral runner" controller="EphemeralRunner" runner="my-runners-a1b2-xk9f2"
"Runner registered" runnerId=1234 jobId="abc-123"
"Pod completed" exitCode=0 phase="Succeeded"

# Retry
"Pod failed, retrying" failures=2 backoff="10s"
"Max failures reached" runner="my-runners-a1b2-xk9f2" failures=5

# Rolling update
"Runner spec hash mismatch, rolling update" old="abc123" new="def456"
"Creating new EphemeralRunnerSet" name="my-runners-e5f6g7h8"
"Draining old EphemeralRunnerSet" name="my-runners-a1b2c3d4"
```

### Common Failure Patterns & Troubleshooting

#### Runner pods stuck in Pending

```
Symptom:  EphemeralRunners in Pending phase, no pods created
Check:    kubectl get ephemeralrunners -n <runner-ns> -o wide
Causes:
  - GitHub API error generating JIT config (check controller logs)
  - Rate limiting on GitHub API
  - K8s RBAC: controller can't create pods in runner namespace
  - Resource quota exhausted in runner namespace
Fix:      Check controller logs for "failed to generate JIT config" errors
```

#### Listener pod CrashLooping

```
Symptom:  Listener pod in CrashLoopBackOff
Check:    kubectl logs <listener-pod> -n <controller-ns>
Causes:
  - Invalid GitHub credentials (App key expired, PAT revoked)
  - GitHub Actions Service unreachable (network/proxy issue)
  - Config secret missing or malformed
  - Session creation failure (scale set deleted from GitHub)
Fix:      Check for "failed to create message session" in logs
          Verify githubConfigSecret exists and is valid
```

#### Runners completing but not scaling down

```
Symptom:  Runner count stays high even when jobs complete
Check:    kubectl get ers -n <runner-ns> -o yaml (check spec.replicas vs status)
Causes:
  - Listener not receiving JobCompleted messages
  - PatchID stuck (listener can't reach K8s API)
  - RBAC: listener can't patch ERS
Fix:      Check listener logs for "failed to patch" errors
          Verify Role/RoleBinding in runner namespace
```

#### Jobs assigned but runners never start

```
Symptom:  GitHub shows jobs "Waiting for a runner", pods exist but never connect
Check:    kubectl logs <runner-pod> -n <runner-ns>
Causes:
  - Runner binary can't reach GitHub (proxy/firewall)
  - JIT config expired (pod took too long to start)
  - Runner image missing required binaries
  - Init container failure (check init container logs)
Fix:      Exec into pod, test connectivity: curl -I https://github.com
          Check for ACTIONS_RUNNER_INPUT_JITCONFIG env var
```

#### Rolling update stuck (old ERS won't drain)

```
Symptom:  Old ERS has runners that never complete
Check:    kubectl get er -n <runner-ns> -l runner-set=<old-ers>
Causes:
  - Runner executing a very long job
  - Runner stuck (OOM, deadlock) but not timing out
  - Eventual strategy: waiting for drain that won't complete
Fix:      For stuck runners: delete the EphemeralRunner CR
          (controller will deregister and clean up)
          For hung jobs: cancel the workflow run in GitHub UI
```

### Key kubectl Commands

```bash
# See all ARC resources
kubectl get autoscalingrunnerset,ephemeralrunnerset,ephemeralrunner -A

# Check scaling state
kubectl get ers -n <runner-ns> -o jsonpath='{.items[*].spec.replicas}'

# Watch runner lifecycle
kubectl get er -n <runner-ns> -w

# Check listener health
kubectl get pods -n <controller-ns> -l app.kubernetes.io/component=listener

# See runner phases
kubectl get er -n <runner-ns> -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,JOB:.status.jobId

# Debug RBAC
kubectl auth can-i patch ephemeralrunnersets --as=system:serviceaccount:<ctrl-ns>:<sa-name> -n <runner-ns>
```

---

## 10. Source Code Reference

### Controller Architecture

The `/manager` binary runs four controllers in a single process:

| Controller | Watches | Primary Responsibility |
|-----------|---------|----------------------|
| AutoscalingRunnerSet | `AutoscalingRunnerSet` | Orchestrates ERS + Listener lifecycle, rolling updates |
| AutoscalingListener | `AutoscalingListener` | Creates/manages listener pod + RBAC + config |
| EphemeralRunnerSet | `EphemeralRunnerSet` | Creates/deletes EphemeralRunners to match replica count |
| EphemeralRunner | `EphemeralRunner` | Manages single runner lifecycle (JIT, pod, cleanup) |

### Key Source Files

| File | Purpose |
|------|---------|
| `controllers/actions.github.com/autoscalingrunnerset_controller.go` | ARS reconcile: hash detection, rolling updates, ERS management |
| `controllers/actions.github.com/autoscalinglistener_controller.go` | Listener reconcile: RBAC, config secret, pod creation |
| `controllers/actions.github.com/ephemeralrunnerset_controller.go` | ERS reconcile: patchID processing, scale up/down |
| `controllers/actions.github.com/ephemeralrunner_controller.go` | ER reconcile: JIT config, pod lifecycle, retries, finalizers |
| `controllers/actions.github.com/resourcebuilder.go` | Constructs K8s objects (pods, roles, secrets, etc.) |
| `cmd/ghalistener/main.go` | Listener binary entrypoint |
| `cmd/ghalistener/scaler/scaler.go` | Scaler: formula, patchID logic, K8s patching |
| `apis/actions.github.com/v1alpha1/` | CRD type definitions, hash functions |

### Decision Trees

**AutoscalingRunnerSet Controller — Main Decision:**
```
Reconcile(ARS)
  |
  ├── ARS being deleted?
  |     └── Yes → cleanUpResources (delete all ERS, listener, RunnerScaleSet)
  |
  ├── No EphemeralRunnerSet exists?
  |     └── Yes → Create first ERS + register RunnerScaleSet with GitHub
  |
  ├── RunnerSetSpecHash mismatch?
  |     └── Yes → Rolling update (strategy-dependent)
  |
  ├── ListenerSpecHash mismatch?
  |     └── Yes → Restart listener (delete + recreate)
  |
  └── Hash() mismatch?
        └── Yes → Update RunnerScaleSet on GitHub (labels, settings)
```

**EphemeralRunner Controller — Pod Status Switch:**
```
Pod exists and terminated:
  |
  ├── All containers succeeded (exit 0)?
  |     └── Phase = Succeeded
  |
  ├── Runner container exit code = 7?
  |     └── Phase = Outdated
  |
  ├── Any init container failed?
  |     └── Record failure, delete pod (retry)
  |
  ├── Runner container failed (other exit code)?
  |     └── HasJob?
  |           ├── Yes → delete EphemeralRunner (can't retry assigned job)
  |           └── No  → delete pod only (retry with new pod)
  |
  └── Pod phase = Running?
        └── Update ER phase to Running, record runnerID
```

### Reconcile Frequency & Triggers

Controllers reconcile on:
- **Watch events:** Create/Update/Delete of owned resources
- **Requeue:** Explicit requeue-after (for backoff, periodic sync)
- **Predicate filters:** Only relevant changes trigger reconcile (e.g., spec changes, not status-only updates)

The EphemeralRunner controller requeues on backoff timers (`5s, 10s, 20s, 40s, 80s`) for retries. The ARS controller requeues periodically to check drain progress during rolling updates.
