import importlib.util
import os
from pathlib import Path
import pytest

path=Path(__file__).resolve().parent.parent/'deployment/local/generate_config.py'
spec=importlib.util.spec_from_file_location('pagdoc_local_configuration',path)
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

def test_local_config_is_private_and_does_not_rotate_existing_secrets(tmp_path):
    target=tmp_path/'private/runtime.env'
    assert module.create_config(target)
    original=target.read_bytes()
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.parent.stat().st_mode & 0o777 == 0o700
    assert module.create_config(target) is False
    assert target.read_bytes()==original
    values=dict(line.split('=',1) for line in original.decode().splitlines())
    assert values['PAGDOC_POSTGRES_PASSWORD'] in values['PAGDOC_DATABASE_URL']
    from cryptography.fernet import Fernet
    Fernet(values['PAGDOC_ENCRYPTION_KEY'].encode())
    assert len(values['PAGDOC_SECRET_KEY'])>=32

def test_separate_installations_receive_different_keys(tmp_path):
    a=tmp_path/'a/runtime.env';b=tmp_path/'b/runtime.env'
    module.create_config(a);module.create_config(b)
    assert a.read_bytes()!=b.read_bytes()

def test_public_config_file_is_rejected_without_modifying_it(tmp_path):
    target=tmp_path/'private/runtime.env';module.create_config(target)
    original=target.read_bytes();os.chmod(target,0o644)
    with pytest.raises(ValueError):module.create_config(target)
    assert target.read_bytes()==original

def test_shared_directory_is_rejected(tmp_path):
    folder=tmp_path/'shared';folder.mkdir(mode=0o755)
    with pytest.raises(ValueError):module.create_config(folder/'runtime.env')
    assert not (folder/'runtime.env').exists()
