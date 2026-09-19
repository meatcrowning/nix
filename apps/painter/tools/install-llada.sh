#!/usr/bin/env bash
# Install the tested native AIO nodes on the ComfyUI host, not on frontends.
set -euo pipefail
comfy_dir=${1:?usage: bash install-llada.sh /path/to/ComfyUI}
node_dir="$comfy_dir/custom_nodes/Comfyui-LLaDa-Image-T8"
revision=b86752916f7d81901be6e99cc2c40d559798caba
patch_file="$(dirname "$(realpath "$0")")/llada-compat.patch"
if [[ ! -e "$node_dir" ]]; then
    git clone https://github.com/T8mars/Comfyui-LLaDa-Image-T8 "$node_dir"
    git -C "$node_dir" checkout --detach "$revision"
fi
[[ $(git -C "$node_dir" rev-parse HEAD) == "$revision" ]] || {
    echo 'Existing LLaDA node revision differs; inspect it before updating.' >&2
    exit 1
}
if git -C "$node_dir" apply --reverse --check "$patch_file" 2>/dev/null; then
    echo 'LLaDA compatibility patch already installed.'
else
    git -C "$node_dir" apply --check "$patch_file"
    git -C "$node_dir" apply "$patch_file"
fi
echo 'LLaDA nodes ready. Restart ComfyUI only when its queue is idle.'
