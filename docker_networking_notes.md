# Docker Notes

## CPU Resource Constraints

### Flags

- `--cpu-period` — Length of the CFS scheduling period in microseconds. Default: `100000` (100ms).
- `--cpu-quota` — Microseconds of CPU time the container can use per period. Default: `-1` (unlimited).
- `--cpus` — Decimal shorthand representing number of CPU cores available.

### Relationship

```
--cpus = --cpu-quota / --cpu-period
```

| Flag | Equivalent | Meaning |
|------|-----------|---------|
| `--cpus=1.5` | `--cpu-quota=150000 --cpu-period=100000` | Up to 1.5 cores |
| `--cpus=0.5` | `--cpu-quota=50000 --cpu-period=100000` | Up to half a core |

- These are hard limits enforced by Linux CFS bandwidth controller (cgroups).
- A container can burst across multiple cores within a period, but total CPU time is capped.

---

## Linux Capabilities and Networking

VPN containers need `NET_ADMIN` capability to create TUN/TAP devices:

```bash
docker run --rm --cap-add=NET_ADMIN --device /dev/net/tun --name vpn my-vpn-app
```

By default, Docker runs with restricted capabilities that don't include `NET_ADMIN`.

---

## Docker Socket Sharing: Bind Mount Paths

When sharing the Docker socket (`/var/run/docker.sock`) into a container, bind mount paths are resolved against the **host's** filesystem, not the parent container's.

```
Host: /etc/nginx/nginx.conf  ← this gets mounted
Parent container: /etc/nginx/nginx.conf  ← ignored by daemon
```

The Docker daemon is a host process — it doesn't know which container issued the request.

---

## Docker Networking: Bridge Mode

### How Containers Reach the Outside World

Every container joins the **bridge** network by default. Docker creates a virtual bridge device acting as a switch.

```
┌─────────────────────────────────────────────────────────┐
│  HOST MACHINE                                           │
│                                                         │
│  ┌───────────┐    ┌───────────┐                        │
│  │Container A│    │Container B│                        │
│  │172.17.0.2 │    │172.17.0.3 │                        │
│  └─────┬─────┘    └─────┬─────┘                        │
│        │  veth          │  veth                         │
│        └───────┬────────┘                               │
│                │                                        │
│       ┌────────┴────────┐                               │
│       │  docker0 bridge │                               │
│       │  172.17.0.1     │  (gateway)                    │
│       └────────┬────────┘                               │
│                │                                        │
│          ┌─────┴─────┐                                  │
│          │ iptables  │  (NAT / routing rules)           │
│          └─────┬─────┘                                  │
│                │                                        │
│       ┌────────┴────────┐                               │
│       │  eth0 (host)    │                               │
│       └────────┬────────┘                               │
└────────────────┼────────────────────────────────────────┘
                 │
            Internet
```

**How it works:**
1. Each container gets its own **net namespace** (isolated network stack)
2. Docker creates a **veth pair** — one end in the container, one end on the bridge
3. The bridge acts as a Layer 2 switch between containers
4. **iptables** rules handle NAT so containers reach the internet via the host

### The Default Bridge Network

```bash
$ docker network inspect bridge
```

```
Name:     bridge
Driver:   bridge
Subnet:   172.17.0.0/16
Gateway:  172.17.0.1
```

### Subnet Sizing Formula

```
Usable hosts = 2^(32 - prefix) - 2

/16  →  2^16 - 2 = 65,534 hosts
/24  →  2^8  - 2 = 254 hosts
```

### Containers on the Same Bridge Can Talk

```
┌──────────────────────────────────────────┐
│  Default Bridge Network (172.17.0.0/16)  │
│                                          │
│  ┌─────────────┐    ┌─────────────┐     │
│  │ Container A │◄──►│ Container B │     │
│  │ 172.17.0.2  │    │ 172.17.0.3  │     │
│  └─────────────┘    └─────────────┘     │
│         ping ✓ (must use IP addresses)   │
└──────────────────────────────────────────┘
```

### Custom Bridge Networks: Isolation by Default

```bash
$ docker network create network-a
$ docker network create network-b
```

```
┌─────────────────────┐     ┌─────────────────────┐
│  Network A          │     │  Network B          │
│  172.18.0.0/16      │     │  172.19.0.0/16      │
│                     │     │                     │
│  ┌─────────────┐    │     │  ┌─────────────┐    │
│  │ Container A │────X──────── │ Container B │    │
│  │ 172.18.0.2  │    │     │  │ 172.19.0.2  │    │
│  └─────────────┘    │     │  └─────────────┘    │
└─────────────────────┘     └─────────────────────┘

         Isolated — cannot ping across bridges
```

### Connecting a Container to Multiple Networks

```bash
$ docker network connect network-b container-a
```

Like adding a second NIC to a VM:

```
┌─────────────────────┐     ┌─────────────────────┐
│  Network A          │     │  Network B          │
│                     │     │                     │
│  ┌───────────────┐  │     │  ┌─────────────┐    │
│  │ Container A   │  │     │  │ Container B │    │
│  │ eth0: .18.0.2 │──┘     │  │ 172.19.0.2  │    │
│  │ eth1: .19.0.3 │────────┼──│             │    │
│  └───────────────┘        │  └─────────────┘    │
└───────────────────────────┼─────────────────────┘
              ping ✓ (now on same network)
```

### Default Bridge vs Custom Bridge

| Feature | Default `bridge` | Custom bridge |
|---------|-----------------|---------------|
| Automatic DNS | No (IP only) | Yes (by container name) |
| Auto-join | Yes | Requires `--net` |
| Isolation from other bridges | Yes | Yes |

### Commands Summary

```bash
docker network ls                          # List networks
docker network inspect bridge              # Inspect a network
docker network create my-network           # Create custom bridge
docker run --net my-network my-image       # Join specific network
docker network connect network-b container # Add container to network
```

### The Big Picture

```
┌─────────────────────────────────────────────────────────────────┐
│  DOCKER HOST                                                    │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐  │
│  │ Default Bridge  │  │   Network A     │  │   Network B    │  │
│  │ 172.17.0.0/16   │  │ 172.18.0.0/16   │  │ 172.19.0.0/16  │  │
│  │  [C1] [C2] [C3] │  │  [C4] [C5]      │  │  [C6]          │  │
│  └────────┬────────┘  └────────┬────────┘  └───────┬────────┘  │
│           │                    │                    │            │
│           └────────────────────┼────────────────────┘            │
│                                │                                 │
│                         ┌──────┴──────┐                          │
│                         │  iptables   │                          │
│                         └──────┬──────┘                          │
│                         ┌──────┴──────┐                          │
│                         │  Host NIC   │                          │
│                         └──────┬──────┘                          │
└────────────────────────────────┼────────────────────────────────┘
                            Internet
```

Each bridge is an isolated L2 domain. Cross-bridge communication requires joining a container to multiple networks or publishing ports.

---

## Exposing Container Ports Between Containers (Port Publishing)

### The Problem

Two containers on **different bridge networks** cannot talk to each other directly:

```
┌─────────────────────────┐          ┌─────────────────────────┐
│  Network A (bridge)     │          │  Network B (bridge)     │
│  172.18.0.0/16          │          │  172.19.0.0/16          │
│                         │          │                         │
│  ┌───────────────────┐  │          │  ┌───────────────────┐  │
│  │ Container A       │  │    ✗     │  │ Container B       │  │
│  │ 172.18.0.2        │  │◄───X────►│  │ 172.19.0.2        │  │
│  │ nc -l -p 80       │  │  No L2   │  │ telnet 172.18.0.2 │  │
│  │ (TCP server)      │  │  path!   │  │ (times out)       │  │
│  └───────────────────┘  │          │  └───────────────────┘  │
│                         │          │                         │
│  Gateway: 172.18.0.1    │          │  Gateway: 172.19.0.1    │
└─────────────────────────┘          └─────────────────────────┘
```

Container B can't reach 172.18.0.2 because that IP is on a different bridge — the broadcast domains are isolated.

### The Solution: Port Publishing (`--publish`)

Map a container's internal port to a port on the **host machine**. The host is reachable from all bridge networks (it's the gateway for each).

```bash
docker container create --network network-a --publish 8080:80 ... container-a
```

### Port Publishing Syntax

```
--publish <HOST_PORT>:<CONTAINER_PORT>

Examples:
  --publish 8080:80       # host:8080 → container:80
  --publish 9443:9443     # same port number outside and inside
  --publish 1234:80       # any free host port works

┌──────────────────────────────────────┐
│  Memory aid:  OUTSIDE : INSIDE       │
│                                      │
│  --publish  8080 : 80                │
│             ────   ──                │
│             host   container         │
│          (outside) (inside)          │
└──────────────────────────────────────┘
```

### How Port Publishing Works (iptables DNAT)

```
┌─────────────────────────────────────────────────────────────────────────┐
│  HOST MACHINE                                                            │
│                                                                          │
│  ┌─────────────────────────┐          ┌─────────────────────────┐       │
│  │  Network A              │          │  Network B              │       │
│  │  172.18.0.0/16          │          │  172.19.0.0/16          │       │
│  │                         │          │                         │       │
│  │  ┌───────────────────┐  │          │  ┌───────────────────┐  │       │
│  │  │ Container A       │  │          │  │ Container B       │  │       │
│  │  │ 172.18.0.2:80     │  │          │  │ 172.19.0.2        │  │       │
│  │  │ (nc -l -p 80)     │  │          │  │                   │  │       │
│  │  └────────▲──────────┘  │          │  └───────┬───────────┘  │       │
│  │           │              │          │          │               │       │
│  │  ┌────────┴────────┐    │          │  ┌───────┴───────┐      │       │
│  │  │ bridge-a        │    │          │  │ bridge-b      │      │       │
│  │  │ (gateway:       │    │          │  │ (gateway:     │      │       │
│  │  │  172.18.0.1)    │    │          │  │  172.19.0.1)  │      │       │
│  │  └────────▲────────┘    │          │  └───────┬───────┘      │       │
│  └───────────┼─────────────┘          └──────────┼──────────────┘       │
│              │                                   │                       │
│              │           ┌──────────────┐        │                       │
│              │           │   iptables   │        │                       │
│              │           │              │        │                       │
│              │           │ RULE:        │        │                       │
│              └───────────┤ host:8080 →  │◄───────┘                       │
│                          │ 172.18.0.2:80│                                │
│                          └──────┬───────┘                                │
│                                 │                                        │
│                          ┌──────┴───────┐                                │
│                          │  Host:8080   │ ← also reachable from outside  │
│                          └──────────────┘                                │
└─────────────────────────────────────────────────────────────────────────┘
```

**iptables** rewrites packets:
- Anything arriving at **host:8080** gets DNAT'd (destination NAT) to **172.18.0.2:80**
- This works because the host is the **gateway** for all bridge networks

### The Connection Path (Container B → Container A via published port)

```
Container B                    Host (iptables)              Container A
172.19.0.2                     172.18.0.1:8080              172.18.0.2:80
    │                               │                           │
    │ ① telnet 172.18.0.1 8080     │                           │
    │  (gateway of Network A,       │                           │
    │   reachable because host      │                           │
    │   owns all gateway IPs)       │                           │
    │──────────────────────────────▶│                           │
    │                               │                           │
    │                               │ ② iptables DNAT:         │
    │                               │   dest 8080 → 172.18.0.2:80
    │                               │──────────────────────────▶│
    │                               │                           │
    │                               │ ③ TCP connection          │
    │◀══════════════════════════════╪═══════════════════════════│
    │         established           │      (via host)           │
    │                               │                           │
    │ ④ "Hello"  ──────────────────────────────────────────────▶│ prints "Hello"
    │ ⑤ "World!" ──────────────────────────────────────────────▶│ prints "World!"
```

**Key**: Container B connects to **172.18.0.1:8080** (Network A's gateway, which is the host) — NOT to 172.18.0.2 directly.

### Why the Gateway IP Works

```bash
# Inside Container B:
$ ip route
default via 172.19.0.1 dev eth0    ← container's default gateway (host)
172.19.0.0/16 dev eth0              ← local network

# The host machine owns ALL gateway IPs:
#   172.18.0.1 (bridge-a)
#   172.19.0.1 (bridge-b)
#   172.17.0.1 (default bridge)
#
# So from Container B, 172.18.0.1 is reachable
# (it's just another IP on the host)
```

### From Your Local Machine (host)

Since port 8080 is published on the host, you can also connect directly:

```
┌────────────────────┐         ┌─────────────────────────────────┐
│  Your terminal     │         │  Docker Host                     │
│                    │         │                                   │
│  $ telnet          │         │  iptables: localhost:8080         │
│    localhost 8080   │────────▶│    → 172.18.0.2:80               │
│                    │         │         │                         │
│  "Hello"  ─────────┼─────────┼────────▶│ Container A prints it  │
│                    │         │         │                         │
└────────────────────┘         └─────────────────────────────────┘
```

### Privileged Ports

```
Port numbers:
  0 ─────── 1023          1024 ─────────── 65535
  ├─ PRIVILEGED ─┤        ├── UNPRIVILEGED ──────┤
  │  Needs root  │        │  Any user can bind   │
  │  (80, 443,   │        │  (8080, 3000, 5000)  │
  │   22, 25)    │        │                      │
  └──────────────┘        └──────────────────────┘
```

Using high-numbered host ports (like 8080) avoids conflicts with system services and permission issues.

### Mac / Windows Caveat

```
┌──────────┐      ┌─────────────┐      ┌───────────────────┐
│ Your Mac │─────▶│ Linux VM    │─────▶│ Container         │
│          │      │ (Docker     │      │                   │
│ localhost│ VPNKit│ Desktop)    │      │ :80               │
│ :8080    │ or   │ :8080       │      │                   │
└──────────┘ SSH  └─────────────┘      └───────────────────┘
             tunnel
```

Docker Desktop uses VPNKit (Mac) or SSH tunnels (Lima) to proxy connections from your actual host into the VM where Docker engine runs. Ports are mapped within the VM first, then forwarded to your machine.

### Port Conflicts

You can only map to ports that are **free** on your host. If another process is already listening on 8080, `--publish 8080:80` will fail at container start.

---

## Host Mode Networking (`--net=host`)

### What Is It?

Host mode removes **all network isolation** between the container and the host. The container shares the host's network stack directly — no bridge, no veth pairs, no NAT.

### Bridge Mode vs. Host Mode

```
┌─────────────────────────────────────────────────────────────────────────┐
│  BRIDGE MODE (default)                                                   │
│                                                                          │
│  ┌───────────────────┐                                                  │
│  │ Container         │                                                  │
│  │ Namespace: own    │                                                  │
│  │ IP: 172.17.0.2    │ ← virtual IP, isolated                           │
│  │ eth0: veth pair   │ ← virtual NIC                                    │
│  └─────────┬─────────┘                                                  │
│            │ veth                                                        │
│  ┌─────────▼─────────┐                                                  │
│  │ docker0 bridge    │ ← virtual switch                                 │
│  └─────────┬─────────┘                                                  │
│            │ iptables (NAT)                                              │
│  ┌─────────▼─────────┐                                                  │
│  │ Host eth0         │ ← real NIC                                       │
│  │ IP: 192.168.1.100 │                                                  │
│  └───────────────────┘                                                  │
│                                                                          │
│  Layers: Container → veth → bridge → iptables → host NIC                │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  HOST MODE (--net=host)                                                  │
│                                                                          │
│  ┌───────────────────┐                                                  │
│  │ Container         │                                                  │
│  │ Namespace: HOST's │ ← shares host's network namespace                │
│  │ IP: 192.168.1.100 │ ← same IP as host                                │
│  │ eth0: HOST's eth0 │ ← same real NIC as host                          │
│  └───────────────────┘                                                  │
│                                                                          │
│  No bridge. No veth. No NAT. No virtual anything.                        │
│  Container IS the host, network-wise.                                    │
│                                                                          │
│  Layers: Container → host NIC (direct)                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### What Gets Shared vs. What Stays Isolated

```
┌─────────────────────────────────────────────────────────┐
│  SHARED (same as host):           STILL ISOLATED:        │
│                                                          │
│  ✓ Network namespace              ✗ Filesystem (own /)   │
│  ✓ IP address(es)                 ✗ PID namespace        │
│  ✓ All network interfaces         ✗ Mount namespace      │
│  ✓ Port space (0-65535)           ✗ User namespace       │
│  ✓ Routing table                                         │
│  ✓ iptables rules (visible)                              │
│  ✓ /etc/hosts, /etc/resolv.conf                          │
└─────────────────────────────────────────────────────────┘
```

### Why Host Mode? (Advantages)

```
┌─────────────────────────────────────────────────────────────────┐
│  1. NO PORT PUBLISHING NEEDED                                    │
│                                                                  │
│     Bridge:  docker run --publish 8080:80 --publish 8081:81 ...  │
│     Host:    docker run --net=host ...   (all ports exposed)     │
│                                                                  │
│     --publish is IGNORED in host mode (nothing to map)           │
│                                                                  │
│  2. SLIGHTLY FASTER (no overhead)                                │
│                                                                  │
│     Bridge: packet → veth → bridge → iptables → host NIC         │
│     Host:   packet → host NIC                                    │
│                                                                  │
│     No virtual ethernet, no NAT translation, no bridge hop       │
│                                                                  │
│  3. REAL IP ADDRESS (no NAT)                                     │
│                                                                  │
│     Bridge: container sees 172.17.0.2 (virtual, behind NAT)      │
│     Host:   container sees 192.168.1.100 (real host IP)          │
│                                                                  │
│     Critical for NAT-sensitive apps like VPN software            │
│                                                                  │
│  4. BIND TO MANY PORTS EASILY                                    │
│                                                                  │
│     No need to declare every port upfront with --publish         │
│     App can dynamically bind to any free port                    │
└─────────────────────────────────────────────────────────────────┘
```

### Trade-offs

| | Bridge mode | Host mode |
|---|---|---|
| Network isolation | Full (own namespace) | None (shares host's) |
| Port conflicts | Container ports are private | Container competes with host processes for ports |
| Security | Contained | Container can sniff host traffic, bind to any port |
| Port publishing | Required (`--publish`) | Not needed (ignored) |
| Performance | Slight overhead (NAT, veth) | Native speed |
| Predictable IPs | Virtual IPs assigned by Docker | Uses host's real IPs |
| Multiple containers same port | Fine (each has own namespace) | Conflict (only one can bind :8080) |

### Example: Running a Server in Host Mode

```bash
# Run container with host networking + interactive mode
docker run --rm -i --net=host --entrypoint nc curlimages/curl -l -p 8080
```

```
┌─────────────────────────────────────────────────────────────────┐
│  HOST MACHINE (192.168.1.100)                                    │
│                                                                  │
│  ┌──────────────────────────────────────────────────────┐       │
│  │  Container (--net=host)                               │       │
│  │                                                       │       │
│  │  nc -l -p 8080                                        │       │
│  │  Listening on: 192.168.1.100:8080  ← host's real IP  │       │
│  │                                                       │       │
│  │  Sees: host's eth0, host's routes, host's ports       │       │
│  └──────────────────────────────────────────────────────┘       │
│                                                                  │
│  From anywhere on the network:                                   │
│  $ telnet 192.168.1.100 8080  ← connects directly, no NAT       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Multiple Ports — No Config Needed

```bash
# Inside a host-mode container, bind to as many ports as you want:
nc -l -p 8080 &
nc -l -p 8081 &
nc -l -p 8082 &

# All immediately accessible from outside — no --publish required
```

```
┌──────────────────────────────────────────────────────┐
│  Host mode container                                  │
│                                                       │
│  :8080 ──── listening (nc)                            │
│  :8081 ──── listening (nc)      All bound directly    │
│  :8082 ──── listening (nc)      on host's interface   │
│                                                       │
│  From another machine:                                │
│  $ telnet 192.168.1.100 8080  ✓                      │
│  $ telnet 192.168.1.100 8081  ✓                      │
│  $ telnet 192.168.1.100 8082  ✓                      │
└──────────────────────────────────────────────────────┘
```

### Port Conflicts in Host Mode

```
┌──────────────────────────────────────────────────────────────┐
│  HOST                                                         │
│                                                               │
│  nginx (host process) ─── listening on :80                    │
│  container (--net=host) ─ tries to bind :80 → ERROR!          │
│                                                               │
│  Same port space = same conflict rules as any host process    │
│  Privileged ports (<1024) still require root                  │
└──────────────────────────────────────────────────────────────┘
```

### When to Use Host Mode

| Use case | Why host mode helps |
|----------|-------------------|
| VPN containers | NAT-sensitive; needs real IPs and TUN/TAP devices |
| Performance-critical networking | Eliminates bridge/NAT overhead |
| Apps binding many dynamic ports | No need to declare ports upfront |
| Monitoring/debugging tools | Needs visibility into host network stack |
| Legacy apps that don't work behind NAT | Sees real IPs, real interfaces |

### When NOT to Use Host Mode

| Scenario | Why bridge is better |
|----------|---------------------|
| Running multiple instances of same app | Port conflicts in host mode |
| Multi-tenant / untrusted containers | No network isolation in host mode |
| Microservices with service discovery | Bridge + DNS is more manageable |
| Production web apps | Port publishing gives controlled exposure |

---

## Summary: Docker Network Drivers

| Driver | Isolation | Ports | Use case |
|--------|-----------|-------|----------|
| **bridge** (default) | Full (own namespace, virtual IP) | Must `--publish` | Most containers |
| **host** | None (shares host namespace) | All exposed automatically | VPN, perf-critical, many-port apps |
| **none** | Full (no networking at all) | N/A | Security-hardened, batch jobs |

| Method | Use case | How |
|--------|----------|-----|
| **Same bridge** | Containers on same network | Direct IP (or DNS on custom bridge) |
| **Join multiple networks** | Container needs full access to another network | `docker network connect` |
| **Port publishing** | Expose specific port(s) to host + all networks | `--publish HOST:CONTAINER` |
| **Host mode** | Expose ALL ports, no isolation | `--network host` |
