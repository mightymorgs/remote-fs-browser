import pytest
from remote_fs_browser import Policy
from remote_fs_browser import discovery


def test_custom_subnet_paginates_without_skipping_or_probing_outside(monkeypatch):
    seen=[]
    def probe(address, **kwargs):
        seen.append(address[0]); raise OSError()
    monkeypatch.setattr(discovery.socket, 'create_connection', probe)
    policy=Policy(network_ranges=['10.0.0.0/8'])
    first=discovery.discover(policy,True,ranges=['10.10.0.0/23'])
    assert first['next_offset']==256
    assert set(seen)=={f'10.10.0.{i}' for i in range(1,256)}|{'10.10.1.0'}
    seen.clear()
    second=discovery.discover(policy,True,ranges=['10.10.0.0/23'],offset=256)
    assert second['next_offset'] is None
    assert set(seen)=={f'10.10.1.{i}' for i in range(1,255)}
    with pytest.raises(PermissionError): discovery.discover(policy,True,ranges=['192.168.2.0/24'])
    with pytest.raises(ValueError): discovery.discover(policy,True,ranges=['bad'])


def test_defaults_can_be_narrower_than_connection_policy():
    policy=Policy(network_ranges=['0.0.0.0/0'],discovery_ranges=['10.10.20.0/24'])
    assert discovery.discover(policy)['scan_ranges']==['10.10.20.0/24']


def test_large_subnet_does_not_expand_in_memory(monkeypatch):
    def probe(*args,**kwargs): raise OSError()
    monkeypatch.setattr(discovery.socket,'create_connection',probe)
    result=discovery.discover(Policy(network_ranges=['0.0.0.0/0']), True, ranges=['10.0.0.0/8'],offset=65536)
    assert result['next_offset']==65792


def test_hypervisor_subnets_preserve_actual_masks():
    from remote_fs_browser.defaults import local_subnets
    assert local_subnets(max_prefix=0,addresses=[('eno1','10.10.3.7','255.255.0.0'),('wlan0','192.168.5.2','255.255.254.0')]) == ['10.10.0.0/16','192.168.4.0/23']
