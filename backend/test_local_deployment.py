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


def test_enabling_files_preserves_existing_private_keys(tmp_path):
    spec=importlib.util.spec_from_file_location('enable_private_files',path.with_name('enable_files.py'))
    feature=importlib.util.module_from_spec(spec);spec.loader.exec_module(feature)
    target=tmp_path/'private/runtime.env';module.create_config(target)
    original=target.read_text()
    feature.enable(target)
    assert target.read_text()==original+'PAGDOC_BINARY_HTTP_ENABLED=1\n'
    assert target.stat().st_mode & 0o777==0o600
    feature.enable(target)
    assert target.read_text()==original+'PAGDOC_BINARY_HTTP_ENABLED=1\n'


def remote_module():
    spec=importlib.util.spec_from_file_location('remote_access',path.with_name('remote_access.py'))
    feature=importlib.util.module_from_spec(spec);spec.loader.exec_module(feature)
    return feature


@pytest.mark.parametrize('address',['0.0.0.0','127.0.0.1','192.168.1.8','8.8.8.8','100.128.0.1','::1','https://100.64.1.2','100.64.1.2\nOTHER=value'])
def test_remote_rejects_non_netbird_or_injected_addresses(address):
    with pytest.raises(ValueError):remote_module().private_ip(address)


def test_remote_requires_connected_management_and_owned_address():
    feature=remote_module();status={'management':{'connected':True},'netbirdIp':'100.64.10.2/16'}
    interfaces=[{'addr_info':[{'family':'inet','local':'100.64.10.2'}]}]
    assert feature.connected_ip(status,interfaces)=='100.64.10.2'
    with pytest.raises(ValueError):feature.connected_ip(status,[])
    with pytest.raises(ValueError):feature.connected_ip({**status,'management':{'connected':False}},interfaces)


def test_remote_configuration_preserves_credentials_and_is_reversible(tmp_path):
    feature=remote_module();runtime=tmp_path/'private/runtime.env';module.create_config(runtime)
    before=runtime.read_bytes();remote=runtime.with_name('remote.env')
    feature.enable(remote,'100.64.10.2')
    assert feature.check_file(remote)=='100.64.10.2'
    assert remote.stat().st_mode&0o777==0o600
    assert runtime.read_bytes()==before
    remote.unlink();assert runtime.read_bytes()==before


def test_remote_rejects_unsafe_file_and_extra_configuration(tmp_path):
    feature=remote_module();folder=tmp_path/'private';folder.mkdir(mode=0o700);remote=folder/'remote.env'
    feature.enable(remote,'100.64.10.2');remote.chmod(0o644)
    with pytest.raises(ValueError):feature.check_file(remote)
    remote.chmod(0o600);remote.write_text('PAGDOC_NETBIRD_IP=100.64.10.2\nPAGDOC_SECRET_KEY=unexpected\n')
    with pytest.raises(ValueError):feature.check_file(remote)
    remote.unlink();remote.symlink_to(folder/'missing')
    with pytest.raises(ValueError):feature.enable(remote,'100.64.10.2')
