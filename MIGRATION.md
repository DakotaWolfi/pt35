# Migration plan

1. Commit this snapshot without touching the running PT35.
2. Collect missing installed scripts using `pt35_missing_export.sh`.
3. Compare Remote Eye controller and collar-pet launcher code to their own repositories before any cross-repo updates.
4. Set up an explicit Git checkout and a deploy script with backups, not direct overwrites.
5. Store NFC archives locally; do not publish Tonie captures or keys.
