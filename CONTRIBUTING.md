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
python3 -m py_compile app.py
node --check static/app.js
./scripts/build_package.sh test
```

Do not commit `config.json`, `data/`, backups, databases, logs, or generated
release archives. User-visible changes belong in `CHANGELOG.md`.
