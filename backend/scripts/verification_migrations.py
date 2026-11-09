"""Exact, immutable named schema boundaries for disposable verification only.

This never changes the production migration runner or applied SQL. Future files
are excluded from an earlier phase; an approved optional predecessor is included
when present. Missing, substituted or unexpected earlier files fail closed.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import tempfile

MANIFEST = Path(__file__).with_suffix('.json')


def digest(path):
    # Git/Windows newline conversion must not make identical SQL incompatible.
    return hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class Phase:
    filenames: tuple[str, ...]
    additions: tuple[str, ...]
    hashes: dict[str, str]
    excluded_later: tuple[str, ...]

    @property
    def count(self):
        return len(self.filenames)

    @property
    def baseline_count(self):
        return self.count - len(self.additions)

    def report(self):
        return dict(terminal=self.filenames[-1], files=list(self.filenames),
                    additions=list(self.additions), hashes=self.hashes,
                    excluded_later=list(self.excluded_later),
                    manifest_sha256=digest(MANIFEST))


def inspect_phase(source, additions, manifest=MANIFEST):
    additions = (additions,) if isinstance(additions, str) else tuple(additions)
    if not additions or len(additions) != len(set(additions)):
        raise ValueError('Distinct named phase additions required')
    data = json.loads(Path(manifest).read_text(encoding='utf-8'))
    if data['format'] != 1:
        raise ValueError('Unsupported verifier manifest')
    known, optional = data['files'], set(data['optional'])
    if any(name not in known or name in optional for name in additions):
        raise ValueError('Unknown phase addition')
    terminal = max(additions)
    # Each upgrade applies only its terminal consecutive suffix, not a hole.
    required = {name for name in known if name <= terminal and name not in optional}
    actual = {p.name: p for p in Path(source).glob('*.sql')}
    selected = {name for name in actual if name <= terminal}
    expected = required | {name for name in optional if name <= terminal and name in actual}
    if selected != expected:
        raise ValueError('Missing or unexpected migration before phase boundary')
    names = tuple(sorted(selected))
    if tuple(sorted(additions)) != names[-len(additions):]:
        raise ValueError('Phase additions must be a consecutive terminal suffix')
    hashes = {name: digest(actual[name]) for name in names}
    if any(hashes[name] != known[name] for name in names):
        raise ValueError('Immutable migration content differs from reviewed manifest')
    return Phase(names, tuple(sorted(additions)), hashes,
                 tuple(sorted(name for name in actual if name > terminal)))


@contextmanager
def phase_migrations(runner, additions, evidence_dir):
    """Install a scoped copy for one verifier; always restore its runner path."""
    original = runner.MIGRATIONS_DIR
    phase = inspect_phase(original, additions)
    with tempfile.TemporaryDirectory(prefix='phase-', dir=evidence_dir) as directory:
        target = Path(directory)
        for name in phase.filenames:
            # Write precisely the reviewed canonical SQL, no substitutions.
            (target / name).write_text((original / name).read_text(encoding='utf-8'),
                                      encoding='utf-8', newline='\n')
            if digest(target / name) != phase.hashes[name]:
                raise ValueError('Migration changed while preparing phase copy')
        runner.MIGRATIONS_DIR = target
        try:
            yield phase
        finally:
            runner.MIGRATIONS_DIR = original
