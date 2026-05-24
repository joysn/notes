# Docker Storage: Volumes

## The Core Problem

Containers are ephemeral — when they stop, their writable layer disappears. Volumes solve this by providing persistent storage that survives container restarts/removal.

## How Volumes Work

```
┌─────────────────────────────────────────────────────┐
│                   HOST MACHINE                        │
│                                                      │
│  Docker System Directory                             │
│  /var/lib/docker/volumes/                            │
│  ┌─────────────────────┐                            │
│  │  my_volume/_data/   │◄── Actual data lives here  │
│  │  ├── file1.txt      │                            │
│  │  └── db.sqlite      │                            │
│  └─────────┬───────────┘                            │
│            │                                         │
│            │ transparent mount                        │
│            ▼                                         │
│  ┌─────────────────────────────────────┐            │
│  │         CONTAINER                    │            │
│  │                                      │            │
│  │  / (root filesystem - ephemeral)     │            │
│  │  ├── bin/                            │            │
│  │  ├── etc/                            │            │
│  │  ├── app/                            │            │
│  │  └── data/ ◄── mount point           │            │
│  │       ├── file1.txt  (from volume)   │            │
│  │       └── db.sqlite  (from volume)   │            │
│  └─────────────────────────────────────┘            │
└─────────────────────────────────────────────────────┘
```

## Container Filesystem (UnionFS) vs Volume

```
┌──────────────────────────────────────────────────┐
│              CONTAINER VIEW                        │
├──────────────────────────────────────────────────┤
│                                                   │
│  ┌────────────────────┐   Thin writable layer     │
│  │  Container Layer   │   (lost on removal)       │
│  │  (read-write)      │                           │
│  ├────────────────────┤                           │
│  │  Image Layer 3     │                           │
│  ├────────────────────┤   Stacked read-only       │
│  │  Image Layer 2     │   image layers            │
│  ├────────────────────┤                           │
│  │  Image Layer 1     │                           │
│  └────────────────────┘                           │
│                                                   │
│  ┌────────────────────┐                           │
│  │  VOLUME mounted    │   Bypasses UnionFS        │
│  │  at /data          │   ← PERSISTS after        │
│  │                    │     container is gone      │
│  └────────────────────┘                           │
└──────────────────────────────────────────────────┘
```

## Volume Driver Architecture

```
         docker volume create my_vol
                    │
                    ▼
        ┌───────────────────┐
        │   Docker Engine    │
        └────────┬──────────┘
                 │
                 ▼
        ┌───────────────────┐
        │   Volume Driver    │    Pluggable!
        ├───────────────────┤
        │ • local (default) │──► creates dir in /var/lib/docker/volumes/
        │ • nfs             │──► mounts remote NFS share
        │ • cifs/samba      │──► mounts Windows/Samba share
        │ • device          │──► mounts block device (e.g. /dev/vda1)
        └───────────────────┘
```

## Local Driver — More Than Just Local

Despite the name "local", it can mount remote storage:

```
┌──────────────────────────────────────────────────────┐
│  Local Volume Driver Options                          │
├────────────┬─────────────────────────────────────────┤
│  type=     │  What it does                            │
├────────────┼─────────────────────────────────────────┤
│  (none)    │  Plain directory on host                 │
│  nfs       │  Mount NFS share from network            │
│  cifs      │  Mount Samba/Windows share               │
│  device    │  Mount block device (safer than          │
│            │  --privileged mode)                      │
└────────────┴─────────────────────────────────────────┘
```

## Data Lifecycle Comparison

```
Container removed:
  ┌────────────┐
  │ Container  │──── GONE ────► writable layer = DELETED
  │ Layer      │
  └────────────┘
  ┌────────────┐
  │ Volume     │──── SAFE ────► data still in /var/lib/docker/volumes/
  └────────────┘


Volume shared between containers:
  ┌────────────┐
  │ Container A│───┐
  └────────────┘   │     ┌──────────┐
                   ├────►│  Volume   │  Same data, both read/write
  ┌────────────┐   │     └──────────┘
  │ Container B│───┘
  └────────────┘
```

## Key Takeaways

1. **Volumes bypass UnionFS** — they're mounted directly, not layered
2. **Managed by drivers** — the `local` driver is default and handles most cases
3. **Persist independently** — survive container stop/remove/crash
4. **Shareable** — multiple containers can mount the same volume
5. **Local driver ≠ local only** — can mount NFS, CIFS, and block devices

---

# Creating Docker Volumes

## The `docker volume create` Command

```
docker volume create [OPTIONS] [VOLUME_NAME]
```

```
┌───────────────────────────────────────────────────────┐
│  docker volume create                                  │
├───────────────────────────────────────────────────────┤
│                                                        │
│  Options:                                              │
│  ┌──────────┬────────────────────────────────────┐    │
│  │  -d      │  Driver (default: "local")          │    │
│  │  -o      │  Driver-specific options (repeatable)│   │
│  │  [name]  │  Name of the volume                 │    │
│  └──────────┴────────────────────────────────────┘    │
│                                                        │
│  Example:                                              │
│  docker volume create -d local super-duper-important   │
│                                                        │
└───────────────────────────────────────────────────────┘
```

## Two Ways to Mount a Volume to a Container

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ┌─────────────────────┐         ┌─────────────────────┐       │
│  │   --mount (long)    │         │   -v (short)         │       │
│  │                     │         │                      │       │
│  │  Explicit key=value │         │  Colon-separated     │       │
│  │  pairs, verbose     │         │  positional args     │       │
│  └──────────┬──────────┘         └──────────┬───────────┘       │
│             │                               │                    │
│             ▼                               ▼                    │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                   CONTAINER                              │    │
│  │                                                          │    │
│  │   Volume mounted at destination path                     │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## `--mount` Syntax (The Long Way)

```
--mount type=volume,source=<vol-name>,destination=<path>[,readonly][,volume-opt=<key>=<val>]
```

```
┌────────────────────────────────────────────────────────────────────┐
│  --mount key=value pairs                                            │
├──────────────┬─────────────────────────────────────────────────────┤
│  Key         │  Description                              Required? │
├──────────────┼─────────────────────────────────────────────────────┤
│  type        │  Mount type: volume, bind, or tmpfs       YES       │
├──────────────┼─────────────────────────────────────────────────────┤
│  source      │  Volume name (from docker volume create)  YES       │
├──────────────┼─────────────────────────────────────────────────────┤
│  destination │  Path inside container to mount at        YES       │
├──────────────┼─────────────────────────────────────────────────────┤
│  readonly    │  Mount as read-only (ro)                  NO        │
├──────────────┼─────────────────────────────────────────────────────┤
│  volume-opt  │  Driver-specific options (repeatable)     NO        │
└──────────────┴─────────────────────────────────────────────────────┘
```

## `-v` Syntax (The Short Way)

```
-v <volume-name>:<destination>[:<options>]
```

```
┌─────────────────────────────────────────────────────────┐
│                                                          │
│  -v  super-duper-important : /super-important : ro       │
│      ├────────────────────┘  ├───────────────┘  ├──┘    │
│      │                       │                  │        │
│      source (vol name)       destination        options  │
│                              (path in           (ro,     │
│                               container)        volume-  │
│                                                 opt)     │
└─────────────────────────────────────────────────────────┘
```

## Mount Types Supported by Docker

```
┌────────────────────────────────────────────────────────┐
│  type=         │  What it is                            │
├────────────────┼───────────────────────────────────────┤
│  volume        │  Docker-managed named volume           │
│  bind          │  Host path mounted directly            │
│  tmpfs         │  In-memory filesystem (no persistence) │
└────────────────┴───────────────────────────────────────┘
```

## Practical Example: Full Walkthrough

```
Step 1: Create the volume
─────────────────────────
$ docker volume create super-duper-important
super-duper-important


Step 2: Run container with volume mounted
──────────────────────────────────────────
$ docker run -it --rm \
    --mount 'type=volume,source=super-duper-important,destination=/super-important' \
    alpine

  Equivalent short form:
  $ docker run -it --rm -v super-duper-important:/super-important alpine


Step 3: What Docker does behind the scenes
──────────────────────────────────────────

  HOST                                    CONTAINER
  ┌─────────────────────────────┐        ┌──────────────────────┐
  │ /var/lib/docker/volumes/    │        │                      │
  │  super-duper-important/     │        │  / (alpine rootfs)   │
  │   _data/                    │◄──────►│  └── super-important/│
  │    └── (empty initially)    │  mount │      └── (empty)     │
  └─────────────────────────────┘        └──────────────────────┘


Step 4: Write data from inside the container
────────────────────────────────────────────
/# echo "hello world" > /super-important/README

  HOST                                    CONTAINER
  ┌─────────────────────────────┐        ┌──────────────────────┐
  │ /var/lib/docker/volumes/    │        │                      │
  │  super-duper-important/     │        │  /super-important/   │
  │   _data/                    │◄──────►│   └── README         │
  │    └── README ("hello world")│ sync  │       "hello world"  │
  └─────────────────────────────┘        └──────────────────────┘


Step 5: Container exits (--rm removes it)
─────────────────────────────────────────

  HOST                                    CONTAINER
  ┌─────────────────────────────┐        ┌──────────────────────┐
  │ /var/lib/docker/volumes/    │        │                      │
  │  super-duper-important/     │        │      GONE! 💀        │
  │   _data/                    │        │                      │
  │    └── README ("hello world")│       └──────────────────────┘
  │         ▲                   │
  │         │                   │
  │     STILL HERE! ✓           │
  └─────────────────────────────┘
```

## `docker volume inspect`

```
$ docker volume inspect super-duper-important

┌────────────────────────────────────────────────────────┐
│  {                                                      │
│    "CreatedAt": "2024-01-15T10:30:00Z",                │
│    "Driver": "local",                                   │
│    "Labels": {},                                        │
│    "Mountpoint": "/var/lib/docker/volumes/              │
│                   super-duper-important/_data",         │
│    "Name": "super-duper-important",                    │
│    "Options": {},                                       │
│    "Scope": "local"                                     │
│  }                                                      │
└────────────────────────────────────────────────────────┘
         │
         ▼
  This is where the actual data lives on the host
```

## When to Use `--mount` vs `-v`

```
┌───────────────────────────────────────────────────────────┐
│  Use -v when...              │  Use --mount when...        │
├──────────────────────────────┼────────────────────────────┤
│  Simple volume mounts        │  Need driver-specific opts  │
│  Quick one-liners            │  Using volume plugins       │
│  Default driver (local)      │  Want explicit/readable     │
│  No special options needed   │  Complex configurations     │
└──────────────────────────────┴────────────────────────────┘
```

## Key Takeaways — Creating Volumes

1. **`docker volume create <name>`** — creates a named volume (local driver by default)
2. **Two mount syntaxes** — `--mount` (verbose, explicit) vs `-v` (concise, positional)
3. **type, source, destination** — the three mandatory keys for `--mount`
4. **Read-only option** — use `readonly` / `ro` to protect sensitive data (passwords, configs)
5. **Data survives container removal** — even with `--rm`, the volume persists
6. **Volume lives at** `/var/lib/docker/volumes/<name>/_data` on the host

---

# Docker Bind Mounts

## The Problem Bind Mounts Solve

```
Scenario: You want to run tests inside a container without rebuilding the image every time.

WITHOUT bind mounts (tedious):
┌──────────────────────────────────────────────────────────────────┐
│                                                                   │
│  1. docker volume create foo                                      │
│  2. docker container create -v foo:/app -w /app --name ctr img   │
│  3. docker cp ./tests ctr:/app        ◄── manual copy every time │
│  4. docker start ctr                                              │
│  5. docker rm ctr                      ◄── cleanup                │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘

WITH bind mounts (simple):
┌──────────────────────────────────────────────────────────────────┐
│                                                                   │
│  docker run --rm -v ./tests:/app alpine sh -c "run tests"        │
│                                                                   │
│  No volumes to manage. No leftover containers. Done.              │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

## Volume vs Bind Mount — Key Difference

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  VOLUME                              BIND MOUNT                         │
│  ┌─────────────────────┐            ┌─────────────────────┐           │
│  │ Docker manages the   │            │ YOU choose the       │           │
│  │ storage location     │            │ host directory       │           │
│  │                      │            │                      │           │
│  │ /var/lib/docker/     │            │ /any/path/on/host    │           │
│  │   volumes/foo/_data  │            │   (you control it)   │           │
│  └──────────┬───────────┘            └──────────┬───────────┘          │
│             │                                   │                       │
│             ▼                                   ▼                       │
│  ┌─────────────────────────────────────────────────────────┐           │
│  │                     CONTAINER                            │           │
│  │       /app (mount point)                                 │           │
│  └─────────────────────────────────────────────────────────┘           │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

## How Bind Mounts Work

```
  HOST MACHINE                              CONTAINER
  ┌────────────────────────────┐           ┌──────────────────────────┐
  │                            │           │                           │
  │  /home/user/project/       │           │  / (container rootfs)     │
  │  ├── src/                  │           │  ├── bin/                 │
  │  ├── tests/                │◄─────────►│  ├── etc/                 │
  │  │   ├── test_1.py         │  direct   │  └── app/  ◄── mount pt  │
  │  │   ├── test_2.py         │  mapping  │      ├── test_1.py       │
  │  │   └── test_3.py         │           │      ├── test_2.py       │
  │  └── Dockerfile            │           │      └── test_3.py       │
  │                            │           │                           │
  └────────────────────────────┘           └──────────────────────────┘

  Changes on EITHER side are immediately visible on the OTHER side.
  (It's the SAME filesystem location, not a copy!)
```

## Common Use Cases for Bind Mounts

```
┌────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  1. HOT RELOADING (frontend development)                           │
│  ┌──────────┐       ┌──────────────────┐                          │
│  │  Editor  │       │    Container     │                          │
│  │          │       │                  │                          │
│  │ edit     │──────►│  webpack/vite    │──► browser auto-refreshes│
│  │ App.jsx  │ bind  │  detects change  │                          │
│  └──────────┘ mount └──────────────────┘                          │
│                                                                     │
│  2. BACKUP/RESTORE Docker volumes                                  │
│     (covered in next section)                                      │
│                                                                     │
│  3. ONE-OFF COMMANDS (e.g., run SQL against a DB)                  │
│  ┌──────────────┐    ┌──────────────────┐                         │
│  │ ./script.sql │───►│ psql container   │──► executes against DB  │
│  └──────────────┘    └──────────────────┘                         │
│                                                                     │
└────────────────────────────────────────────────────────────────────┘
```

## `--mount` Syntax for Bind Mounts (The Long Way)

```
--mount type=bind,source=<host-path>,destination=<container-path>[,readonly][,bind-propagation=<opt>]
```

```
┌────────────────────────────────────────────────────────────────────────┐
│  --mount key=value pairs (bind mount)                                   │
├──────────────────┬─────────────────────────────────────────────────────┤
│  Key             │  Description                              Required? │
├──────────────────┼─────────────────────────────────────────────────────┤
│  type            │  Must be "bind"                            YES      │
├──────────────────┼─────────────────────────────────────────────────────┤
│  source          │  Absolute path on HOST machine             YES      │
├──────────────────┼─────────────────────────────────────────────────────┤
│  destination     │  Path inside container (created if needed) YES      │
├──────────────────┼─────────────────────────────────────────────────────┤
│  readonly        │  Mount as read-only                        NO       │
├──────────────────┼─────────────────────────────────────────────────────┤
│  bind-propagation│  How sub-mounts propagate (advanced)       NO       │
├──────────────────┼─────────────────────────────────────────────────────┤
│  selinux-label   │  :z (shared) or :Z (private) for SELinux   NO       │
└──────────────────┴─────────────────────────────────────────────────────┘
```

## `-v` Syntax for Bind Mounts (The Short Way)

```
-v <host-path>:<container-path>[:<options>]
```

```
┌──────────────────────────────────────────────────────────────┐
│                                                               │
│  -v  /tmp/lima/stuff : /stuff : ro                            │
│      ├──────────────┘  ├─────┘  ├──┘                         │
│      │                 │        │                             │
│      source            dest     options                       │
│      (HOST path,       (path    (ro, z, Z,                    │
│       must be          in       bind-propagation)             │
│       absolute*)       container)                             │
│                                                               │
│  * On some systems, relative paths like ./dir won't work.     │
│    Use $PWD/dir or $(realpath ./dir) instead.                 │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

## Gotcha: Non-Existent Source Path with `-v`

```
⚠️  WARNING: If the source path doesn't exist when using -v,
    Docker creates a DIRECTORY (not a file) at that path on the host!

  $ docker run -v /tmp/oops/myfile.txt:/app/config.txt alpine cat /app/config.txt

  What you expect:
  ┌─────────────────┐         ┌─────────────────────────┐
  │ /tmp/oops/      │         │ /app/config.txt (file)  │
  │  myfile.txt ←───┼─────────┤                         │
  └─────────────────┘         └─────────────────────────┘

  What actually happens (source didn't exist):
  ┌─────────────────┐         ┌──────────────────────────┐
  │ /tmp/oops/      │         │ /app/config.txt (DIR!) ← │ ERROR!
  │  myfile.txt/ ◄──┼─ Docker │  It's a directory now    │
  │  (empty dir)    │ created └──────────────────────────┘
  └─────────────────┘  this

  Solution: Make sure the source file/dir exists BEFORE running the container.
```

## Practical Example: Full Walkthrough

```
Step 1: Create test files on host
──────────────────────────────────
$ mkdir -p /tmp/lima/stuff
$ for x in $(seq 1 10); do echo "this is file number $x" > /tmp/lima/stuff/file-$x; done

  HOST: /tmp/lima/stuff/
  ├── file-1   ("this is file number 1")
  ├── file-2   ("this is file number 2")
  ├── ...
  └── file-10  ("this is file number 10")


Step 2: Bind mount into container and read a file
─────────────────────────────────────────────────
$ docker run --rm -v /tmp/lima/stuff:/stuff alpine cat /stuff/file-3
this is file number 3

  HOST                              CONTAINER
  ┌─────────────────────┐         ┌────────────────────┐
  │ /tmp/lima/stuff/     │◄──────►│ /stuff/             │
  │  ├── file-1          │  bind  │  ├── file-1         │
  │  ├── file-2          │  mount │  ├── file-2         │
  │  ├── file-3  ◄───────┼───────►│  ├── file-3 ◄─ cat │
  │  └── ...             │        │  └── ...            │
  └─────────────────────┘         └────────────────────┘


Step 3: Write FROM container → appears on host
──────────────────────────────────────────────
$ docker run --rm -v /tmp/lima/stuff:/stuff alpine \
    sh -c 'echo "this is file number 10" > /stuff/file-10'

  CONTAINER writes to /stuff/file-10
         │
         ▼ (same filesystem!)
  HOST: /tmp/lima/stuff/file-10 now exists!

$ cat /tmp/lima/stuff/file-10
this is file number 10


Step 4: Using relative paths (portability)
──────────────────────────────────────────
  # May fail on some systems:
  $ docker run -v ./stuff:/stuff alpine ls /stuff

  # Safe alternatives:
  $ docker run -v $PWD/stuff:/stuff alpine ls /stuff
  $ docker run -v $(realpath ./stuff):/stuff alpine ls /stuff
```

## Bi-Directional Sync Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  HOST filesystem                    CONTAINER filesystem         │
│                                                                  │
│  /tmp/lima/stuff/                   /stuff/                      │
│  ┌──────────────┐                  ┌──────────────┐             │
│  │              │                  │              │             │
│  │  file-1      │◄────────────────►│  file-1      │             │
│  │  file-2      │  SAME INODES    │  file-2      │             │
│  │  file-3      │  (not a copy!)  │  file-3      │             │
│  │              │                  │              │             │
│  └──────────────┘                  └──────────────┘             │
│        │                                  │                      │
│        ▼                                  ▼                      │
│  Edit on host?                     Edit in container?            │
│  → Instantly visible               → Instantly visible           │
│    in container                       on host                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Volume vs Bind Mount — When to Use Which

```
┌─────────────────────────────────────────────────────────────────────┐
│  Use VOLUMES when...             │  Use BIND MOUNTS when...          │
├──────────────────────────────────┼───────────────────────────────────┤
│  Data must persist after         │  Sharing source code with         │
│  container is removed            │  container (dev workflow)          │
│                                  │                                    │
│  Don't care where data lives     │  Need a specific host path        │
│  on host                         │  accessible in container           │
│                                  │                                    │
│  Want Docker to manage storage   │  Hot reloading / live editing      │
│                                  │                                    │
│  Production data (DB, logs)      │  One-off scripts / config files    │
│                                  │                                    │
│  Need volume driver features     │  Backing up/restoring volumes      │
│  (NFS, cloud storage)            │                                    │
└──────────────────────────────────┴───────────────────────────────────┘
```

## Key Takeaways — Bind Mounts

1. **Bind mounts map host directories directly** — no volume driver, no Docker-managed storage
2. **Bi-directional** — changes on host appear in container and vice versa (same inodes)
3. **`type=bind`** in `--mount`, or just use an absolute host path with `-v`
4. **Absolute paths required** on some systems — use `$PWD` or `realpath` for portability
5. **Non-existent source with `-v` creates a directory** — a common gotcha when mounting files
6. **No leftover state** — no volume to clean up after the container is gone
7. **Great for dev workflows** — hot reload, test running, one-off commands

---

# Backing Up and Restoring Docker Volumes

## Why Not Just Copy from the Host Path?

```
$ docker volume inspect super-duper-important
→ Mountpoint: /var/lib/docker/volumes/super-duper-important/_data

⚠️  You COULD scp/cp from this path, but DON'T rely on it because:

┌────────────────────────────────────────────────────────────────────┐
│  Driver          │  Where data actually lives                       │
├──────────────────┼─────────────────────────────────────────────────┤
│  local           │  /var/lib/docker/volumes/<name>/_data (OK)      │
│  NFS driver      │  Remote NFS server (not on local disk!)         │
│  Cloud driver    │  Object storage (S3, Azure Blob, etc.)          │
│  Custom driver   │  May transform data on write (not raw files)    │
└──────────────────┴─────────────────────────────────────────────────┘

Solution: Back up INSIDE a container — works with ANY driver.
└────────────────────────────────────────────────────────────────────┘
```

## The Strategy: Combine Volume Mount + Bind Mount

```
┌────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│  TEMPORARY CONTAINER (--rm, disposable)                                │
│  ┌───────────────────────────────────────────────────────────────┐    │
│  │                                                                │    │
│  │   /backup    ◄── volume mount (data to back up)                │    │
│  │   /target    ◄── bind mount ($PWD on host)                     │    │
│  │                                                                │    │
│  │   tar czf /target/backup.tar -C /backup .                     │    │
│  │        │                                                       │    │
│  │        └── compress /backup contents → save to /target         │    │
│  │                                                                │    │
│  └───────────────────────────────────────────────────────────────┘    │
│         │                          │                                    │
│         ▼                          ▼                                    │
│  ┌──────────────┐          ┌──────────────────┐                       │
│  │  VOLUME      │          │  HOST: $PWD/     │                       │
│  │  (source)    │          │  backup.tar ✓    │                       │
│  └──────────────┘          └──────────────────┘                       │
│                                                                         │
└────────────────────────────────────────────────────────────────────────┘
```

## Backup Command — Step by Step

```
$ docker run --rm \
    -v $PWD:/target \
    -v super-duper-important:/backup \
    alpine tar cvzf /target/backup.tar -C /backup .
```

```
Breaking it down:

docker run --rm                          ← disposable container
  -v $PWD:/target                        ← bind mount: host CWD → /target
  -v super-duper-important:/backup       ← volume mount: data → /backup
  alpine                                 ← lightweight image
  tar cvzf /target/backup.tar            ← create gzipped archive at /target
      -C /backup                         ← cd into /backup first
      .                                  ← compress everything in current dir
```

```
What happens inside the container:

  ┌───────────────────────────────────────────────────────────────┐
  │  CONTAINER                                                     │
  │                                                                │
  │  /backup/              (volume: super-duper-important)         │
  │  ├── README            ← data we want to back up              │
  │  └── other-files                                               │
  │                                                                │
  │         │  tar compresses                                      │
  │         ▼                                                      │
  │                                                                │
  │  /target/              (bind mount: $PWD on host)              │
  │  └── backup.tar        ← archive lands here                   │
  │                                                                │
  └───────────────────────────────────────────────────────────────┘
           │
           ▼
  HOST: $PWD/backup.tar now exists on your machine!
```

## Why `-C /backup .` Instead of Just `/backup`?

```
WITHOUT -C (bad):
  tar czf backup.tar /backup
  → Archive contains: backup/README, backup/other-files
  → Restoring creates: ./backup/README  (extra nesting!)

WITH -C (good):
  tar czf backup.tar -C /backup .
  → Archive contains: ./README, ./other-files
  → Restoring creates: ./README  (flat, clean!)

┌───────────────────────────────────────────────────────┐
│  Without -C              │  With -C /backup .          │
├──────────────────────────┼────────────────────────────┤
│  backup/                 │  ./                         │
│   └── README             │   └── README               │
│                          │                             │
│  To access after restore:│  To access after restore:  │
│  /restore/backup/README  │  /restore/README ← clean!  │
└──────────────────────────┴────────────────────────────┘
```

## Verify the Backup

```
$ tar -tf backup.tar
./
./README

  -t = list contents (don't extract)
  -f = specify file

  For production: extract and compare checksums rather than just listing.
```

## Restore Command — The Reverse Process

```
Step 1: Create a new volume to restore into
────────────────────────────────────────────
$ docker volume create super-duper-important-restore


Step 2: Extract backup into the new volume
──────────────────────────────────────────
$ docker run --rm \
    -v $PWD:/target \
    -v super-duper-important-restore:/restore \
    alpine tar xvf /target/backup.tar -C /restore .
```

```
What happens inside the container:

  ┌───────────────────────────────────────────────────────────────┐
  │  CONTAINER                                                     │
  │                                                                │
  │  /target/              (bind mount: host $PWD)                 │
  │  └── backup.tar        ← the backup we took earlier           │
  │                                                                │
  │         │  tar extracts                                        │
  │         ▼                                                      │
  │                                                                │
  │  /restore/             (volume: super-duper-important-restore) │
  │  └── README            ← data restored!                        │
  │                                                                │
  └───────────────────────────────────────────────────────────────┘
           │
           ▼
  VOLUME: super-duper-important-restore now has our data!
```

## Verify the Restore

```
$ docker run --rm -v super-duper-important-restore:/restore alpine cat /restore/README
hello world   ← Success!
```

## Full Backup/Restore Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                          │
│  BACKUP                                                                  │
│  ══════                                                                  │
│                                                                          │
│  ┌──────────────┐     ┌───────────────┐     ┌───────────────────┐      │
│  │   Volume     │────►│  Container    │────►│  Host ($PWD)      │      │
│  │   (source)   │ -v  │  runs tar czf │ -v  │  backup.tar       │      │
│  └──────────────┘     └───────────────┘     └───────────────────┘      │
│                                                                          │
│                                                                          │
│  RESTORE                                                                 │
│  ═══════                                                                 │
│                                                                          │
│  ┌───────────────────┐     ┌───────────────┐     ┌──────────────┐      │
│  │  Host ($PWD)      │────►│  Container    │────►│  New Volume  │      │
│  │  backup.tar       │ -v  │  runs tar xvf │ -v  │  (restored)  │      │
│  └───────────────────┘     └───────────────┘     └──────────────┘      │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Key Takeaways — Volume Backup/Restore

1. **Don't rely on host paths** — volume drivers may store data in NFS, cloud, etc.
2. **Use a throwaway container** with both a volume mount (source) and bind mount (output)
3. **`tar czf`** to back up, **`tar xvf`** to restore — standard Unix tools
4. **`-C <dir> .`** avoids unwanted directory nesting in the archive
5. **Works with ANY volume driver** — because you access data from inside the container
6. **Verify backups** — `tar -tf` for quick checks, checksums for production
