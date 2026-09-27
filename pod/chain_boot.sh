#!/usr/bin/env bash
cd /root/g4 && chmod 600 /root/.kaggle/kaggle.json
pgrep -f '^bash pod/supervisor.sh' >/dev/null || setsid nohup bash pod/supervisor.sh > /root/supervisor.out 2>&1 < /dev/null &
bash pod/bootstrap.sh > /root/boot.out 2>&1
bash pod/harness_env.sh > /root/henv.out 2>&1
bash pod/buildenv.sh > /root/benv.out 2>&1
bash pod/serve2.sh > /root/serve.out 2>&1
echo "BOOT_CHAIN_DONE $(date -u +%FT%TZ)" >> /root/chain.log
