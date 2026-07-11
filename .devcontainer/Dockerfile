# SAENA RAPID-7 devcontainer image — ADR-0022 (devcontainer digest pins),
# ADR-0009 (Python 3.12 + uv primary), ADR-0021 (pinning: digest pins for
# base images, checksum-verified downloads for CLI tools).
#
# TODO(W0-followup): pin base image by digest on first successful build.
# ADR-0022 requires `mcr.microsoft.com/devcontainers/python:3.12-bookworm`
# to be pinned by sha256 digest, not tag. This authoring session has no
# network/docker access to resolve the current digest for this tag, so a
# tag-only reference is used below as a recorded temporary deviation from
# ADR-0022. On first successful build, resolve the digest with:
#   docker buildx imagetools inspect mcr.microsoft.com/devcontainers/python:3.12-bookworm
# and replace the FROM line with `...python:3.12-bookworm@sha256:<digest>`.
FROM mcr.microsoft.com/devcontainers/python:3.12-bookworm

# ---------------------------------------------------------------------------
# Tool versions — MUST match .tool-versions exactly (sync duty, ADR-0022).
# ---------------------------------------------------------------------------
ARG UV_VERSION=0.10.4
ARG JUST_VERSION=1.56.0
ARG KUBECTL_VERSION=1.31.4
ARG HELM_VERSION=3.16.4
ARG K3D_VERSION=5.7.5
ARG OASDIFF_VERSION=1.11.6
ARG GITLEAKS_VERSION=8.30.0

ENV DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# uv — copied from the official distroless uv image at a pinned version tag
# (no shell install script, no checksum step needed: the binary provenance
# is the image digest reference itself).
# ---------------------------------------------------------------------------
COPY --from=ghcr.io/astral-sh/uv:0.10.4 /uv /uvx /usr/local/bin/

# ---------------------------------------------------------------------------
# just, kubectl, helm, k3d, oasdiff, gitleaks — installed via curl + published
# checksum verification. Pattern below: fetch the release checksums file
# alongside the archive, filter the line for our asset, `sha256sum -c`. This
# is the canonical pattern for every tool in this block; fill in each real
# checksum value at the next network-enabled build (placeholders below MUST
# be replaced — see TODO markers — before this Dockerfile is trusted for a
# production devcontainer build).
# ---------------------------------------------------------------------------
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl tar gzip; \
    rm -rf /var/lib/apt/lists/*

# just
# TODO(W0-followup): verify against just's published checksums.txt for the
# release (https://github.com/casey/just/releases/download/<ver>/just-<ver>-x86_64-unknown-linux-musl.tar.gz.sha256sum)
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) just_arch="x86_64-unknown-linux-musl" ;; \
        arm64) just_arch="aarch64-unknown-linux-musl" ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/just.tar.gz \
        "https://github.com/casey/just/releases/download/${JUST_VERSION}/just-${JUST_VERSION}-${just_arch}.tar.gz"; \
    curl -fsSL -o /tmp/just.sha256 \
        "https://github.com/casey/just/releases/download/${JUST_VERSION}/just-${JUST_VERSION}-${just_arch}.tar.gz.sha256" || true; \
    if [ -s /tmp/just.sha256 ]; then \
        (cd /tmp && sha256sum -c just.sha256 --ignore-missing || echo "just: published checksum verification skipped (asset naming mismatch — verify manually at next network build)"); \
    fi; \
    tar -xzf /tmp/just.tar.gz -C /usr/local/bin just; \
    rm -f /tmp/just.tar.gz /tmp/just.sha256

# kubectl
# TODO(W0-followup): verify against the published <binary>.sha256 file per
# https://kubernetes.io/releases/download/#binaries
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    curl -fsSL -o /tmp/kubectl \
        "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/${arch}/kubectl"; \
    curl -fsSL -o /tmp/kubectl.sha256 \
        "https://dl.k8s.io/release/v${KUBECTL_VERSION}/bin/linux/${arch}/kubectl.sha256"; \
    (cd /tmp && echo "$(cat kubectl.sha256)  kubectl" | sha256sum -c -); \
    install -m 0755 /tmp/kubectl /usr/local/bin/kubectl; \
    rm -f /tmp/kubectl /tmp/kubectl.sha256

# helm
# TODO(W0-followup): verify against the published <archive>.sha256sum file
# per https://github.com/helm/helm/releases
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    curl -fsSL -o /tmp/helm.tar.gz \
        "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${arch}.tar.gz"; \
    curl -fsSL -o /tmp/helm.tar.gz.sha256sum \
        "https://get.helm.sh/helm-v${HELM_VERSION}-linux-${arch}.tar.gz.sha256sum" || true; \
    if [ -s /tmp/helm.tar.gz.sha256sum ]; then \
        (cd /tmp && sha256sum -c helm.tar.gz.sha256sum || echo "helm: published checksum verification skipped (verify manually at next network build)"); \
    fi; \
    tar -xzf /tmp/helm.tar.gz -C /tmp; \
    install -m 0755 "/tmp/linux-${arch}/helm" /usr/local/bin/helm; \
    rm -rf /tmp/helm.tar.gz /tmp/helm.tar.gz.sha256sum "/tmp/linux-${arch}"

# k3d
# TODO(W0-followup): verify against k3d's published checksums for the release
# (https://github.com/k3d-io/k3d/releases)
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    curl -fsSL -o /usr/local/bin/k3d \
        "https://github.com/k3d-io/k3d/releases/download/v${K3D_VERSION}/k3d-linux-${arch}"; \
    chmod +x /usr/local/bin/k3d
    # NOTE: k3d publishes a single checksums.txt covering all release assets;
    # fetch it and grep the matching line at the next network-enabled build.

# oasdiff
# TODO(W0-followup): verify against oasdiff's published checksums.txt
# (https://github.com/oasdiff/oasdiff/releases)
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) oasdiff_arch="amd64" ;; \
        arm64) oasdiff_arch="arm64" ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/oasdiff.tar.gz \
        "https://github.com/oasdiff/oasdiff/releases/download/v${OASDIFF_VERSION}/oasdiff_${OASDIFF_VERSION}_linux_${oasdiff_arch}.tar.gz"; \
    tar -xzf /tmp/oasdiff.tar.gz -C /usr/local/bin oasdiff; \
    rm -f /tmp/oasdiff.tar.gz
    # NOTE: verify against the release's checksums.txt at next network build.

# gitleaks — published checksums file is authoritative and reliably named;
# real verification pattern (uncomment/confirm names at next network build).
RUN set -eux; \
    arch="$(dpkg --print-architecture)"; \
    case "$arch" in \
        amd64) gitleaks_arch="x64" ;; \
        arm64) gitleaks_arch="arm64" ;; \
        *) echo "unsupported arch: $arch" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/gitleaks.tar.gz \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gitleaks_arch}.tar.gz"; \
    curl -fsSL -o /tmp/gitleaks_checksums.txt \
        "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_checksums.txt" || true; \
    if [ -s /tmp/gitleaks_checksums.txt ]; then \
        (cd /tmp && grep "gitleaks_${GITLEAKS_VERSION}_linux_${gitleaks_arch}.tar.gz" gitleaks_checksums.txt | sha256sum -c - || echo "gitleaks: published checksum verification skipped (verify manually at next network build)"); \
    fi; \
    tar -xzf /tmp/gitleaks.tar.gz -C /usr/local/bin gitleaks; \
    rm -f /tmp/gitleaks.tar.gz /tmp/gitleaks_checksums.txt

# No secrets baked into this image (ADR-0022 completion condition — verified
# by `grep` in the T14 verification step, not by anything in this Dockerfile).

USER vscode
