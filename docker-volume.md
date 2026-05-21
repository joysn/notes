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
