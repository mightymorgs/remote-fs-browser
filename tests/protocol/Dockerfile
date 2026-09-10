FROM debian:bookworm-slim
RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq samba nfs-ganesha nfs-ganesha-mem && rm -rf /var/lib/apt/lists/*
RUN mkdir -p /share /run/ganesha && chmod 777 /share && useradd -M tester && printf 'protocol-test-password\nprotocol-test-password\n' | smbpasswd -a -s tester
COPY smb.conf /etc/samba/smb.conf
COPY ganesha.conf /etc/ganesha/ganesha.conf
CMD ["sh", "-c", "rpcbind -w; smbd -D && exec ganesha.nfsd -F -L /dev/stdout"]
