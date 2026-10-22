# Unraid

Install from the Apps tab. Search for **Crowbarr**. Choose **Crowbarr** for CPU processing
or **Crowbarr-CUDA** for an NVIDIA GPU.

Until the Community Applications listing is live, add the template repository by hand:
open **Docker**, **Add Container**, **Template repositories**, and enter
`https://github.com/amanofvaly/unraid-templates`. Save, then pick the template from the
**Template** list.

## Fill in the form

- **WebUI**: host port, 8449 by default.
- **Path: /tv** and **Path: /movies**: the same shares Sonarr and Radarr use. Matching the
  container paths means no path mappings to configure later. Leave one empty if you do
  not have that library.
- **Path: /data** (advanced): use instead when Sonarr and Radarr see a single `/data` share.
- **Appdata** (advanced): `/mnt/user/appdata/crowbarr`. Unraid creates it.

The container runs as `nobody:users` (99:100), the Unraid default for shares. Crowbarr
writes subtitles next to your videos, so read-only shares will not work. The user is set
in **Extra Parameters** under the advanced view; change it there if your shares use a
different owner.

Press **Apply**. Open the WebUI, create your account, then add Sonarr, Radarr and Plex
under Settings. Speech models download into appdata on first use.

## NVIDIA

Install the **Nvidia Driver** plugin from Apps first. In the Crowbarr-CUDA template, set
**NVIDIA_VISIBLE_DEVICES** to the GPU UUID shown on the plugin page, or leave `all`.
After the first start, select CUDA under **Settings**. Until you do, it runs on the CPU.

## Intel Arc A770

Use **`ghcr.io/jmello86/crowbarr:intel`** from this fork. It runs Whisper on PyTorch
XPU, with CPU language verification and subtitle timing refinement. There is no
dedicated Intel Community Applications template yet; edit your existing container
or configure it manually.

On the Unraid terminal, locate the A770's render node and its numeric group:

```sh
ls -l /dev/dri/by-path/
stat -c '%g' /dev/dri/renderD128
```

Match the PCI address to your A770 if you have multiple GPUs. Substitute its render
node throughout the instructions (it may be `renderD129`). The card must be available
to the Unraid host, rather than bound to VFIO for a VM. If no render node exists,
enable the Intel GPU driver for your Unraid version before proceeding.

Pull the Intel image from the Unraid terminal, or let the Docker form pull it:

```sh
docker pull ghcr.io/jmello86/crowbarr:intel
```

Edit your existing Crowbarr container in Unraid, enable **Advanced View**, and:

- Set **Repository** to `ghcr.io/jmello86/crowbarr:intel`.
- Remove `--runtime=nvidia` or `--gpus` from Extra Parameters, if present, and remove
  `NVIDIA_VISIBLE_DEVICES` and `NVIDIA_DRIVER_CAPABILITIES` variables.
- Add a **Device** with host path `/dev/dri/renderD128` and container path
  `/dev/dri/renderD128` (use the A770's actual host path).
- Keep `--user 99:100` and add `--group-add NUMBER` in **Extra Parameters**, replacing
  `NUMBER` with the group ID returned by `stat`. Retain other unrelated parameters.
- Keep your existing appdata and media path mappings, then press **Apply**.

Under **Settings → Processing**, choose **Intel GPU · XPU** and **FP16**. Saved CUDA
settings do not switch automatically. Download your selected model if requested;
Intel uses reference Whisper checkpoints in `/config/models/whisper-xpu`, alongside
the faster-whisper models used for CPU fallback. Allow extra disk space for both.

Check the GPU from the container console, which runs with its configured identity:

```sh
python -c 'import torch; print(torch.xpu.is_available()); print(torch.xpu.get_device_name(0)); print(torch.ones(1, device="xpu").cpu())'
```

It should print `True`, the Intel device name, and a tensor. Run a job and check its
runtime report for `xpu`; `cpu` with a fallback reason means GPU inference failed.
Disable CPU fallback while diagnosing failures if you want the job to stop instead.
Intel GPU memory telemetry is not currently shown on the dashboard.

Hardware detection runs in the background at startup and can take around 30 seconds
while the inference and alignment libraries initialize. Version 0.4.13 allows up to
two minutes; earlier builds stopped after 20 seconds and could incorrectly report a
working GPU as unavailable. If you encounter that timeout on 0.4.12, update and
recreate the container. Completing the integration settings or downloading speech
models is not required for detection.

Unraid can check the published tag for updates. Pull the newer image and recreate
the container to apply them. `latest-intel` is an alias for `intel`; commit tags such
as `sha-COMMIT-intel` and digests can pin a specific build for rollback.

The unpacked image is roughly 7–8 GB, plus separate appdata space for models. If
you prefer a local build, use `Dockerfile.intel` and allow at least 12 GB of free
Docker storage. Local images must be rebuilt manually after source changes.

CI verifies packages, real speech on CPU, and server startup. It has no Intel GPU;
the device check and a job report above are needed to confirm A770 execution.

## Update

Unraid checks the image tag on its schedule and shows **update ready** on the Docker
page. Press it. Appdata, paths and settings are untouched.

## Troubleshooting

Open the container log from the Docker page. For permission errors, check that
`nobody:users` can write to the share, and that the appdata folder is not owned by root.
