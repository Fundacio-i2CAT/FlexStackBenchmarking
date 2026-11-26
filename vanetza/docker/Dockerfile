# Build the Vanetza benchmark harness as a self-contained bundle:
#   /bundle/flexstack-bench-vanetza   the binary
#   /bundle/lib/                      its shared libraries (all but glibc's)
#   /bundle/run.sh                    LD_LIBRARY_PATH launcher
#   /bundle/VANETZA_COMMIT
# Built on Ubuntu 24.04 (Vanetza needs a recent GCC and Boost). The bundle
# carries every shared library including glibc and its loader, and run.sh
# starts the binary through that loader: it runs on older systems too (the
# laptop's Mint 20.3 has glibc 2.31) and on newer ones (RPi OS / Debian 13).
FROM ubuntu:24.04 AS build
# Retried: an Ubuntu mirror that is being synced serves index files that fail
# their size or hash check ("Mirror sync in progress?") for a few minutes.
RUN for i in 1 2 3 4 5; do \
        apt-get -o Acquire::Retries=3 update \
        && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
            build-essential ca-certificates cmake ninja-build \
            libboost-date-time-dev libboost-program-options-dev libboost-system-dev \
            libcrypto++-dev libgeographiclib-dev libssl-dev \
        && break; \
        [ "$i" = 5 ] && exit 1; \
        echo "apt failed (attempt $i), retrying in 60 s"; rm -rf /var/lib/apt/lists/*; sleep 60; \
    done \
    && rm -rf /var/lib/apt/lists/*
COPY vanetza /src/vanetza
RUN cmake -S /src/vanetza -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release -DBUILD_SOCKTAP=ON \
    && cmake --build /build --target socktap
COPY bench_node /src/vanetza/tools/bench_node
RUN echo 'add_subdirectory(tools/bench_node)' >> /src/vanetza/CMakeLists.txt \
    && cmake -S /src/vanetza -B /build \
    && cmake --build /build --target flexstack-bench-vanetza
RUN set -e; mkdir -p /bundle/lib; \
    bin=$(find /build -name flexstack-bench-vanetza -type f -perm -u+x | head -1); \
    cp "$bin" /bundle/; \
    ldd "$bin" | awk '/=> \//{print $3} /^\t\/.*ld-linux/{print $1}' | sort -u | xargs -r -I{} cp -L {} /bundle/lib/; \
    loader=$(cd /bundle/lib && ls ld-linux-*.so.* | head -1); \
    cp /src/vanetza/VANETZA_COMMIT /bundle/; \
    printf '#!/bin/sh\n# Start the harness with the bundled glibc and libraries.\nd=$(dirname "$(readlink -f "$0")")\nexec "$d/lib/%s" --library-path "$d/lib" "$d/flexstack-bench-vanetza" "$@"\n' "$loader" > /bundle/run.sh; \
    chmod +x /bundle/run.sh; ls -la /bundle /bundle/lib

FROM scratch
COPY --from=build /bundle /
