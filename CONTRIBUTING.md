# Contributing to HomeStart

HomeStart intentionally uses the Python standard library, PyYAML, and plain
HTML/CSS/JavaScript so it remains easy to install on a small Linux server.

## Development

```sh
cp config.example.json config.json
PORT=8080 python3 app.py
```

Before opening a pull request, run:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q app.py homestart
node --check static/app.js
./scripts/build_package.sh
python3 scripts/test_update_matrix.py \
  --update "dist/homestart-update-$(cat VERSION).tar.gz" \
  --installer "dist/homestart-installer-$(cat VERSION).tar.gz"
```

Do not commit `config.json`, `data/`, backups, databases, logs, or generated
release archives. User-visible changes belong in `CHANGELOG.md`.

The CI environment also runs `scripts/test_compose_integration.py` against a
real two-service Docker Compose project. It intentionally remains separate from
the portable unit suite because it requires a Docker daemon.

Put new domain logic in the closest `homestart/` package and keep
`homestart/server.py` focused on orchestration. Compatibility wrappers are
preferred while existing server functions are being migrated.
