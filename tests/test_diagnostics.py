from pathlib import Path
import json
import tempfile
import zipfile

from nativehtmlkit.diagnostics import DiagnosticRecorder, _safe, export_bundle
from nativehtmlkit import diagnostics


def test_redaction_never_stores_secrets_payload_or_paths():
    fields=_safe({'token':'token_value','html':'<form>secret</form>',
                  'path':'/home/one/.ssh/id_rsa','password':'12345',
                  'duration_ms':14,'method':'window.create','error_message':'my secret is here'})
    assert fields['token']=='[REDACTED]'
    assert fields['password']=='[REDACTED]'
    assert fields['html']=='[REDACTED]'
    assert fields['path']=='[REDACTED]'
    assert fields['duration_ms']==14
    assert fields['method']=='window.create'
    assert fields['error_message']=='[REDACTED]'


def test_debug_jsonl_and_bounded_history():
    with tempfile.TemporaryDirectory() as tmp:
        recorder=DiagnosticRecorder(level='trace',directory=Path(tmp),max_history=3,max_pending=8)
        for i in range(5):
            recorder.record('rpc.completed',level='TRACE',duration_ms=i,secret='do-not-emit')
        recorder._pending.join();recorder.close()
        assert len(recorder.history())==3
        text=recorder.path.read_text()
        assert 'do-not-emit' not in text
        assert '[REDACTED]' in text
        assert recorder.summary()['records']==3


def test_support_bundle_never_includes_environment_variables(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        monkeypatch.setenv('PRIVATE_API_KEY','do-not-emit')
        path=export_bundle(Path(tmp)/'report.zip',capture_environment=True)
        with zipfile.ZipFile(path) as z:
            assert set(z.namelist())=={'manifest.json','timeline.jsonl'}
            assert 'do-not-emit' not in ''.join(z.read(n).decode() for n in z.namelist())
