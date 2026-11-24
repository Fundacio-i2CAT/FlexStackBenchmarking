# Interop image: Vanetza (pinned) + the Vanetza interop node, and a Python
# environment with the FlexStack revision under test.
#
# Built by ../build.sh, which stages the build context:
#   vanetza/               Vanetza source at the pinned commit (git archive)
#   vanetza_node/          this repository's interop/vanetza_node
#   wheels/*.whl           FlexStack wheel from PyPI (version of python/requirements.txt)
#
# The FlexStack Rust interop node is not built here: build.sh compiles it on
# the host (same Ubuntu 24.04 glibc) and run_interop.sh mounts it.

ARG UBUNTU=ubuntu:24.04

FROM ${UBUNTU} AS vanetza
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        build-essential ca-certificates cmake ninja-build \
        libboost-date-time-dev libboost-program-options-dev libboost-system-dev \
        libcrypto++-dev libgeographiclib-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*
# Vanetza source at the pinned commit, exported by ../build.sh (git archive;
# the commit is recorded in VANETZA_COMMIT).
COPY vanetza /src/vanetza
# Vanetza and socktap first (cached), then the interop node only.
RUN cmake -S /src/vanetza -B /build -G Ninja -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SOCKTAP=ON -DCMAKE_INSTALL_PREFIX=/opt/vanetza \
    && cmake --build /build
COPY vanetza_node /src/vanetza/tools/interop_node
RUN echo 'add_subdirectory(tools/interop_node)' >> /src/vanetza/CMakeLists.txt \
    && cmake -S /src/vanetza -B /build \
    && cmake --build /build \
    && cmake --install /build
RUN cp /src/vanetza/VANETZA_COMMIT /opt/vanetza/VANETZA_COMMIT

FROM ${UBUNTU}
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        ca-certificates iproute2 tcpdump python3 python3-venv \
        libboost-date-time1.83.0 libboost-program-options1.83.0 libboost-system1.83.0 \
        libcrypto++8t64 libgeographiclib26 libssl3t64 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=vanetza /opt/vanetza /opt/vanetza
COPY wheels /tmp/wheels
RUN python3 -m venv /opt/flexstack \
    && /opt/flexstack/bin/pip install --no-cache-dir /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels
ENV PATH=/opt/vanetza/bin:/opt/flexstack/bin:$PATH \
    LD_LIBRARY_PATH=/opt/vanetza/lib
WORKDIR /interop
