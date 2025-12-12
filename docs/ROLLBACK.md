# LLTune Rollback Guide

This document describes the backup bundle produced by `lltune`, what `lltune rollback` restores, and what still requires manual steps.

## Backup Location

By default, backups are stored at:

```
/var/lib/lltune/backups/backup-YYYYMMDDHHMMSS/
```

If `/var/lib/lltune` is not writable, LLTune falls back to:

```
~/.lltune/backups/backup-YYYYMMDDHHMMSS/
```

You can override the location with `LLTUNE_BACKUP_ROOT`.

## Backup Bundle Structure

```
backup-YYYYMMDDHHMMSS/
├── config.yaml
├── snapshot.json
├── baseline/
│   ├── etc/default/grub
│   ├── etc/sysctl.d/99-latency-tuner.conf
│   ├── etc/fstab
│   ├── boot/grub2/grub.cfg                      # if present
│   ├── boot/efi/EFI/<distro>/grub.cfg           # if present
│   └── ethtool/
│       ├── <nic>.features
│       ├── <nic>.coalesce
│       ├── <nic>.rings
│       └── <nic>.flowctrl
└── persistence/                                 # staged only (not installed)
    ├── nic-restore.sh
    ├── thp-setup.sh
    ├── irq-affinity.sh
    ├── workqueue-isolate.sh
    ├── 99-lltune.conf
    ├── lltune-nic-restore.service
    ├── lltune-thp-setup.service
    ├── lltune-irq-affinity.service
    ├── lltune-workqueue.service
    └── README.txt
```

## What Apply Can Auto-Rollback

If `lltune apply` fails mid-run, LLTune will restore any files it backed up and modified during that run.

It cannot reliably undo runtime-only changes such as:

- Live `swapoff` state (use `swapon --all` after restoring `/etc/fstab`)
- Live `/sys` and `/proc` changes (IRQ affinity, RPS/RFS, some NIC settings)
- Hugepage allocations already committed

## Using `lltune rollback`

```bash
sudo lltune rollback --backup /var/lib/lltune/backups/backup-YYYYMMDDHHMMSS/
```

Rollback performs (best effort):

1. Restore:
   - `/etc/default/grub`
   - `/etc/sysctl.d/99-latency-tuner.conf`
   - `/etc/fstab`
2. Regenerate `grub.cfg` for BIOS and/or detected EFI path
3. Disable and remove installed LLTune persistence units:
   - `lltune-nic-restore.service`
   - `lltune-thp-setup.service`
   - `lltune-irq-affinity.service`
   - `lltune-workqueue.service`
4. Reload sysctl settings (`sysctl --system`)

**Reboot required:** If kernel cmdline settings were changed, reboot after rollback.

## Manual Rollback (If Needed)

### Restore GRUB defaults

```bash
sudo cp /var/lib/lltune/backups/backup-*/baseline/etc/default/grub /etc/default/grub
sudo grub2-mkconfig -o /boot/grub2/grub.cfg
```

On EFI systems, also regenerate the detected EFI grub.cfg (example for AlmaLinux):

```bash
sudo grub2-mkconfig -o /boot/efi/EFI/almalinux/grub.cfg
```

### Restore sysctl

```bash
sudo cp /var/lib/lltune/backups/backup-*/baseline/etc/sysctl.d/99-latency-tuner.conf /etc/sysctl.d/99-latency-tuner.conf
sudo sysctl --system
```

### Restore `/etc/fstab` and swap

```bash
sudo cp /var/lib/lltune/backups/backup-*/baseline/etc/fstab /etc/fstab
sudo swapon --all
```

### Disable LLTune persistence services (if installed)

```bash
sudo systemctl disable --now lltune-nic-restore lltune-thp-setup lltune-irq-affinity lltune-workqueue || true
sudo rm -f /etc/systemd/system/lltune-nic-restore.service /etc/systemd/system/lltune-thp-setup.service /etc/systemd/system/lltune-irq-affinity.service /etc/systemd/system/lltune-workqueue.service
sudo systemctl daemon-reload
```
