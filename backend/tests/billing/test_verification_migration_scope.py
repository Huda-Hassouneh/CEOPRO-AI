"""Offline regression for exact phase selection; never starts Docker or libpq."""
from pathlib import Path
from types import SimpleNamespace
import ast
import json
import shutil

import pytest

from scripts.verification_migrations import MANIFEST, digest, inspect_phase, phase_migrations

SOURCE = Path(__file__).resolve().parents[2] / 'src/infrastructure/database/migrations'
OPTIONAL = '20261130000000_custom_discount_approval_guard.sql'
PHASES = [
    (('20261201000000_provider_binding_foundation.sql', '20261201000100_trial_checkout_reservations.sql'), 167),
    (('20261202000000_customer_creation_operations.sql',), 168),
    (('20261203000000_trusted_trial_observations.sql',), 169),
    (('20261204000000_trusted_trial_confirmation.sql',), 170),
    (('20261205000000_recurring_consent_foundation.sql',), 171),
    (('20261206000000_trial_evidence_progression.sql',), 172),
    (('20261207000000_consent_withdrawal_fencing.sql',), 173),
    (('20261208000000_subscription_journey_dispatch.sql',), 174),
    (('20261212000000_definitive_checkout_retry.sql',), 178),
]


@pytest.mark.parametrize('additions,count', PHASES)
def test_later_dependency_files_do_not_enter_an_earlier_upgrade(additions, count):
    phase = inspect_phase(SOURCE, additions)
    assert phase.count == count + int((SOURCE / OPTIONAL).exists())
    assert phase.baseline_count == phase.count - len(additions)
    assert phase.filenames[-1] == max(additions)
    assert not set(phase.excluded_later) & set(phase.filenames)
    assert set(phase.filenames) | set(phase.excluded_later) == {p.name for p in SOURCE.glob('*.sql')}


@pytest.fixture
def copied(tmp_path):
    source = tmp_path / 'sql'
    shutil.copytree(SOURCE, source)
    return source


@pytest.mark.parametrize('damage', ['missing_predecessor', 'missing_new', 'changed_sql', 'extra_early', 'replaced_same_count'])
def test_missing_changed_and_unknown_files_fail_before_runner_use(copied, damage):
    additions = PHASES[1][0]
    previous = copied / PHASES[0][0][0]
    if damage == 'missing_predecessor':
        previous.unlink()
    elif damage == 'missing_new':
        (copied / additions[0]).unlink()
    elif damage == 'changed_sql':
        previous.write_text(previous.read_text() + '\nGRANT ALL ON billing_gateway_bindings TO PUBLIC;\n')
    else:
        if damage == 'replaced_same_count':
            previous.unlink()
        (copied / '20261129000000_unreviewed.sql').write_text('SELECT 1;')
    with pytest.raises(ValueError):
        inspect_phase(copied, additions)


@pytest.mark.parametrize('additions', [(), ('unknown.sql',), (PHASES[0][0][0], PHASES[0][0][0]),
    (PHASES[0][0][0], PHASES[1][0][0])])
def test_invalid_or_nonconsecutive_phase_is_rejected(additions):
    with pytest.raises(ValueError):
        inspect_phase(SOURCE, additions)


def test_future_unknown_file_is_excluded_and_reported(copied):
    (copied / '20270101000000_future.sql').write_text('SELECT 1;')
    phase = inspect_phase(copied, PHASES[0][0])
    assert '20270101000000_future.sql' in phase.report()['excluded_later']
    assert '20270101000000_future.sql' not in phase.filenames


def test_normalized_git_line_endings_remain_compatible(copied):
    p = copied / PHASES[0][0][0]
    p.write_bytes(p.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    assert inspect_phase(copied, PHASES[0][0]).count >= 167


def test_scoped_copy_restores_runner_and_preserves_source_on_failure(tmp_path):
    runner = SimpleNamespace(MIGRATIONS_DIR=SOURCE)
    before = {p.name: p.read_bytes() for p in SOURCE.glob('*.sql')}
    with pytest.raises(RuntimeError, match='injected verifier failure'):
        with phase_migrations(runner, PHASES[0][0], tmp_path) as scope:
            temporary = runner.MIGRATIONS_DIR
            assert {p.name for p in temporary.glob('*.sql')} == set(scope.filenames)
            assert scope.count >= 167
            raise RuntimeError('injected verifier failure')
    assert runner.MIGRATIONS_DIR == SOURCE
    assert not temporary.exists()
    assert before == {p.name: p.read_bytes() for p in SOURCE.glob('*.sql')}


def test_manifest_identifies_the_only_optional_predecessor():
    data = json.loads(MANIFEST.read_text())
    assert data['optional'] == [OPTIONAL]
    assert len(data['files']) == 179
    assert set(data['files']) - {p.name for p in SOURCE.glob('*.sql')} <= {OPTIONAL}


@pytest.mark.parametrize('present', [False, True])
def test_optional_predecessor_changes_only_the_exact_baseline(tmp_path, present):
    old, optional, new = '01.sql', '02.sql', '03.sql'
    for name in (old, optional, new):
        (tmp_path / name).write_text('SELECT ' + name[:2] + ';')
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps(dict(format=1, optional=[optional],
        files={name: digest(tmp_path / name) for name in (old, optional, new)})))
    if not present:
        (tmp_path / optional).unlink()
    phase = inspect_phase(tmp_path, (new,), manifest)
    assert phase.filenames == ((old, optional, new) if present else (old, new))
    assert phase.baseline_count == 1 + int(present)


@pytest.mark.parametrize('name', [
    'verify_payment_persistence', 'verify_customer_operations',
    'verify_verification_observations', 'verify_trial_confirmation',
    'verify_recurring_consent', 'verify_evidence_progression',
    'verify_authenticated_consent', 'verify_subscription_journey',
    'verify_multi_gateway_billing',
])
def test_phase_cleanup_cannot_skip_owned_container_teardown(name):
    script = Path(__file__).resolve().parents[2] / 'scripts' / (name + '.py')
    tree = ast.parse(script.read_text(encoding='utf-8'))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    outer = next(n for n in main.body if isinstance(n, ast.Try) and n.finalbody)
    cleanup = outer.finalbody[0]
    assert isinstance(cleanup, ast.Try)
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and isinstance(n.func.value, ast.Name) and n.func.value.id == 'phase_stack'
               and n.func.attr == 'close' for n in ast.walk(cleanup.body[0]))
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
               and n.func.id == 'docker' and any(isinstance(a, ast.Constant) and a.value == 'stop' for a in n.args)
               for node in cleanup.finalbody for n in ast.walk(node))
