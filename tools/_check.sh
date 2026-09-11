echo '== plugins dir =='
ls -la /mnt/mmc1-4/musicfree-plugins/
echo '== /plugins API =='
curl -s http://127.0.0.1:5001/plugins
echo
echo '== docker ps (bridge+dlna) =='
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'bridge|dlna-speaker'
echo '== disk space =='
df -h /mnt/mmc1-4 | tail -1