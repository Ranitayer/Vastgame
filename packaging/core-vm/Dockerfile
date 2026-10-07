# BASE_IMAGE must be the digest-pinned official Vast KVM wrapper.
ARG BASE_IMAGE
FROM ${BASE_IMAGE}
COPY ubuntu.img /root/images/ubuntu.img
# Inherit Vast's supervisor/entrypoint; never replace it with a Docker SSH server.
