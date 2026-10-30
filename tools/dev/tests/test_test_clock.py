"""No provider access: launcher opt-in and configuration inheritance contracts."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import dev

class ClockLauncherTests(unittest.TestCase):
    def test_explicit_optin_is_local_and_not_inherited_or_copied_to_test_suites(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(dev,'STATE',Path(directory)):
            c={'id':'a'*12,'ports':dict(dev.PORTS),'admin_password':'admin','app_password':'app','storage_password':'storage','jwt':'test','vault':'test'}
            file=Path(directory)/'integrations.env'
            file.write_text('STRIPE_SECRET_KEY=sk_test_offline\nSTRIPE_WEBHOOK_SECRET=whsec_offline\nSTRIPE_TEST_CLOCK_ENABLED=true\nSTRIPE_TEST_CLOCK_ID=clock_fixture\n')
            with patch.dict(os.environ,{'STRIPE_TEST_CLOCK_ID':'clock_inherited'}):
                env=dev.environment(c)
                self.assertEqual(env['STRIPE_TEST_CLOCK_ID'],'clock_fixture')
                self.assertEqual(env['KEEL_LOCAL_TEST_CLOCKS'],'1')
                isolated=dev.environment(c,external=False)
                self.assertEqual(isolated['STRIPE_TEST_CLOCK_ENABLED'],'false')
                self.assertNotIn('KEEL_LOCAL_TEST_CLOCKS',isolated)
            file.write_text('STRIPE_TEST_CLOCK_ENABLED=false\nSTRIPE_TEST_CLOCK_ID=ignored\n')
            self.assertNotIn('KEEL_LOCAL_TEST_CLOCKS',dev.environment(c))
            file.write_text('KEEL_LOCAL_TEST_CLOCKS=1\n')
            with self.assertRaises(dev.DevError):dev.integrations()

    def test_enabled_missing_or_invalid_clock_is_actionable(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(dev,'STATE',Path(directory)):
            file=Path(directory)/'integrations.env'
            for clock in ('','not-clock'):
                file.write_text('STRIPE_SECRET_KEY=sk_test_offline\nSTRIPE_WEBHOOK_SECRET=whsec_offline\nSTRIPE_TEST_CLOCK_ENABLED=true\nSTRIPE_TEST_CLOCK_ID='+clock+'\n')
                with self.assertRaises(dev.DevError):dev.integrations()
