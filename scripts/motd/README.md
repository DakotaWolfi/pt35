# PT35 SSH welcome banner

Adapted from the VisionPi welcome screen. Requires Bash and standard Raspberry Pi OS command-line utilities.

Install (from the repository root):

```sh
sudo install -m 755 scripts/motd/10-pt35 /etc/update-motd.d/10-pt35
sudo /etc/update-motd.d/10-pt35
```

Disable any older custom PT35 banner before enabling this one, to avoid duplication. This is a text login MOTD, not the graphical boot splash. Battery percentage/current can be added after the MAX17055 board is integrated.
