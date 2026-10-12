"""Where saltpod's code lives, and where its data lives: two roots, not one.

    CODE_ROOT   the source tree: bin/, src/, the page. Job steps run with it
                as their working directory and import from its `src`.
    DATA_ROOT   data/, backups/, reports/. `SALTPOD_HOME` when it is set,
                otherwise the source tree, which is where the data has
                always lived -- so nothing moves for anyone who never sets it.

WHY TWO. Fifteen modules each worked out one `ROOT` from their own file and
used it for both jobs: `ROOT/bin/export_playlists.js` is code, `ROOT/data/
state.json` is data. A single override could not repoint that `ROOT`
without breaking the `bin/` and `src/` lookups, and without an override
every test, fixture and second client had only the owner's real data to run
against. Each module now imports the one it means.

    SALTPOD_HOME=/tmp/fixture-home saltpod curate --no-open

A SALTPOD_HOME THAT IS NOT A DIRECTORY IS REFUSED, not created. Every
writer under it would otherwise make its own folder somewhere nobody meant,
and the first sign would be a state file that "lost" every decision.

Imported both ways, like the rest of the package: `from .paths import ...`
inside the package, `from paths import ...` by the modules that are also run
straight from this directory.
"""
import os

CODE_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _data_root():
    home = os.environ.get('SALTPOD_HOME')
    if not home:
        return CODE_ROOT
    home = os.path.abspath(os.path.expanduser(home))
    if not os.path.isdir(home):
        raise SystemExit('SALTPOD_HOME=%s is not a directory -- make it first, or unset it '
                         'to use the data in the source tree' % home)
    return home


DATA_ROOT = _data_root()
