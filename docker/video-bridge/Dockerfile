FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --no-user-group --gid users --create-home --shell /usr/sbin/nologin video \
    && passwd -d video \
    && mkdir -p /run/sshd /keys /host-keys
COPY sshd_config /etc/ssh/sshd_config
COPY entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh
EXPOSE 2222
ENTRYPOINT ["/entrypoint.sh"]
