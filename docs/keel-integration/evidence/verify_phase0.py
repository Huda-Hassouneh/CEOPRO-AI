"""Current read-only documentation/source verifier; historical result JSONs preserved."""
from pathlib import Path
import runpy
if __name__ == '__main__':
    evidence=Path(__file__).parent
    choices=['phase0v/verify_phase0v_documents.py','owner-decisions/verify_owner_decisions.py','phase0r/verify_phase0r.py']
    runpy.run_path(str(next(evidence/x for x in choices if (evidence/x).exists())),run_name='__main__')
