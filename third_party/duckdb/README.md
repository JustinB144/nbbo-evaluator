# DuckDB C++ dependency

Version: **1.5.5**, Linux amd64 (glibc). Pinned header and shared library from
the same official release archive. This is a project-local dependency.

Official source:
https://github.com/duckdb/duckdb/releases/download/v1.5.5/libduckdb-linux-amd64.zip

Archive SHA-256, checked against the GitHub release asset digest on 2026-09-28:

```text
1fb8ce388157d84a25abe685a8a2520bf00c00321821968e4bb398fd766e7abb
```

Installed from that archive: `duckdb.hpp`, `duckdb.h`, `libduckdb.so`.
The static library was not extracted. The release license is saved as `LICENSE`.

The repository Makefile finds the header here, links this library and embeds a runtime
search path relative to the executable. No Python runtime is needed by the
learner's program. The pinned version matches the existing local reference
query environment; it is not described as the latest release.

To reproduce the dependency, download the archive from the official URL,
verify the digest above, and extract those three files into this directory.
