from pathlib import Path
from nativehtmlkit.scaffold import templates,create_project

def test_scaffold_is_rebranded(tmp_path):
    files=templates('Hello NHK','/usr/bin/python3')
    assert 'from nativehtmlkit import Application' in files['app.py']
    assert 'nativehtmlkit>=0.1.0' in files['pyproject.toml']
    assert 'nativehtmlkit-python-host run --app app.toml' in files['app.toml']
    root=tmp_path/'app'
    assert len(create_project(root,name='Hello NHK'))==5
    assert (root/'app.py').exists()
