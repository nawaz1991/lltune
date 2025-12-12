# LLTune Operations Guide

Audience: platform/SRE engineers applying low-latency tuning on AlmaLinux/RHEL9 bare-metal hosts.

## Running the CLI

- `lltune scan --format yaml --output snapshot.yaml --md-report report.md` – capture current state (read-only).
- `lltune gen-config --snapshot snapshot.yaml -o lltune-config.yaml` – build a commented config template.
- `lltune audit -c lltune-config.yaml` – validate schema and cross-check against the live host; fails on errors.
- `lltune apply --plan -c lltune-config.yaml` – dry-run, creates a backup bundle with plan + persistence artifacts and no system changes. Full apply runs the same validation checks and requires root.

## Backups and Persistence Artifacts

- Backups are placed under `/var/lib/lltune/backups/<id>/` by default (or `~/.lltune/backups/<id>/` when permissions block `/var`). The path is printed during `apply --plan`.
- Each bundle contains:
  - `config.yaml`, `snapshot.json` (exact inputs).
  - `persistence/` with:
    - `nic-restore.sh` and `lltune-nic-restore.service` – reapply ethtool offload toggles for configured interfaces.
    - `thp-setup.sh` and `lltune-thp-setup.service` – reapply THP runtime mode and hugepage counts.
    - `irq-affinity.sh` and `lltune-irq-affinity.service` – reapply IRQ affinity rules.
    - `workqueue-isolate.sh` and `lltune-workqueue.service` – move kernel workqueues/kthreads off isolated CPUs (optional).
    - `99-lltune.conf` – resource limits file for `/etc/security/limits.d/` (memlock/nofile/nproc/rtprio).
    - `README.txt` – quick install/rollback notes.
- Persistence files are **staged only**. To persist across reboot:
  - `sudo cp persistence/*.service /etc/systemd/system/`
  - `sudo systemctl daemon-reload`
  - `sudo systemctl enable lltune-nic-restore.service lltune-thp-setup.service lltune-irq-affinity.service`
  - (Optional) `sudo systemctl enable lltune-workqueue.service`
  - **Important**: these service files reference scripts in the backup bundle via `ExecStart`. Keep that bundle path intact or edit `ExecStart` to point at a stable install location.
  - For resource limits: `sudo cp persistence/99-lltune.conf /etc/security/limits.d/` (log out/in to take effect).

## Rollback Guidance (Manual)

- **GRUB cmdline**: restore `/etc/default/grub` from the backup bundle, then run `grub2-mkconfig` for BIOS/UEFI as applicable. Reboot to take effect.
- **Sysctl**: replace `/etc/sysctl.d/99-latency-tuner.conf` with the backed-up copy and run `sudo sysctl --system`.
- **THP/Hugepages**: disable installed `lltune-thp-setup.service` (`systemctl disable --now ...`), restore original THP defaults (`echo always > .../enabled`), and revert hugepage counts as needed.
- **Swap**: re-enable swap devices in `/etc/fstab` and run `swapon --all`.
- **NIC settings**: stop `lltune-nic-restore.service` if enabled, then reapply vendor defaults or use `ethtool -K/-C/-G/-A` based on the baseline captured in the snapshot (saved in the backup bundle).
- **IRQ affinity / workqueues**: stop `lltune-irq-affinity.service` / `lltune-workqueue.service` if enabled; reboot if needed.
- **Resource limits**: remove `99-lltune.conf` from `/etc/security/limits.d/` if you installed it; log out/in to take effect.
- **Services**: re-enable `irqbalance` or tuned profiles if they were disabled for tuning.
- **CLI helper**: `lltune rollback --backup <path-to-bundle>` will restore the backed-up GRUB defaults, sysctl snippet, fstab, and grub.cfg variants best-effort; follow with `grub2-mkconfig` if GRUB files were restored.
- Always reference the backup ID printed during `apply --plan` to locate the right bundle. If multiple changes were applied, work from the newest bundle backward.

## Examples

Sample configs live under `examples/` for common topologies (single-socket Mellanox, dual-socket mixed NICs, lab template). Adjust isolated cores, NIC roles, and PTP interface before use.
