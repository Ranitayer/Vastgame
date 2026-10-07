# BASE_IMAGE must be the digest-pinned official Vast KVM wrapper.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.source="https://github.com/Ranitayer/Vastgame"
COPY ubuntu.img /root/images/ubuntu.img
# Inherit Vast's supervisor/entrypoint; never replace it with a Docker SSH server.
