# Confluent Docker Utils
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Fconfluentinc%2Fconfluent-docker-utils.svg?type=shield)](https://app.fossa.com/projects/git%2Bgithub.com%2Fconfluentinc%2Fconfluent-docker-utils?ref=badge_shield)


This project includes common logic for testing Confluent's Docker images.

For more information, see: https://docs.confluent.io/platform/current/installation/docker/development.html#docker-utility-belt-dub


## Extending the Java CLASSPATH

The `cub` utility now supports extending the Java CLASSPATH at runtime via environment variables:

- `CUB_CLASSPATH` (existing): overrides the entire base classpath when set. Keep quotes if you pass it as a single value.
- `CUB_CLASSPATH_DIRS` (new): append one or more directories to the base classpath.
  - Accepts multiple entries separated by `:`, `;` or `,`.
  - Each directory is normalized to include all jars within it (a trailing `/*` is added if missing).
  - The final CLASSPATH is kept quoted to avoid shell expansion issues.
  - The final classpath separator is always `:` (Linux/JVM convention in Confluent images).
- `CUB_EXTRA_CLASSPATH` (legacy fallback): used only if `CUB_CLASSPATH_DIRS` is not set.

Examples:
- Linux: set `CUB_CLASSPATH_DIRS=/opt/libs:/opt/plugins,/usr/share/java/custom`
- Windows host (executing inside Linux containers): set `CUB_CLASSPATH_DIRS=C:\\libs;C:\\plugins` — entries are parsed but the resulting CLASSPATH uses `:` between segments.

If neither `CUB_CLASSPATH_DIRS` nor `CUB_EXTRA_CLASSPATH` is provided, the default base classpath is used.

## License
[![FOSSA Status](https://app.fossa.com/api/projects/git%2Bgithub.com%2Fconfluentinc%2Fconfluent-docker-utils.svg?type=large)](https://app.fossa.com/projects/git%2Bgithub.com%2Fconfluentinc%2Fconfluent-docker-utils?ref=badge_large)
