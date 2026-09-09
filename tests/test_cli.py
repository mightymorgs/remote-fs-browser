from remote_fs_browser.cli import main, addresses


def test_serve_defaults_and_explicit_binding(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('uvicorn.run', lambda app, **options: calls.append((app, options)))
    main(['serve'])
    app, options = calls[-1]
    assert options['host'] == '127.0.0.1' and options['port'] == 8080
    assert app.state.browser.policy.local_roots == [str(tmp_path)]
    assert 'Browser login token:' in capsys.readouterr().out
    main(['serve', '--bind', '0.0.0.0', '--port', '8081', '--root', str(tmp_path), '--allow-network', '192.0.2.0/24'])
    app, options = calls[-1]
    assert options['host'] == '0.0.0.0' and options['port'] == 8081
    assert app.state.browser.policy.network_ranges == ['192.0.2.0/24']


def test_legacy_config_launch(tmp_path, monkeypatch):
    import json
    config = tmp_path / 'config.json'
    config.write_text(json.dumps({'token':'x'*32, 'port':8765, 'policy':{'local_roots':[]}}))
    calls = []
    monkeypatch.setattr('uvicorn.run', lambda app, **options: calls.append(options))
    main(['--config', str(config)])
    assert calls[0]['port'] == 8765
    assert addresses('100.82.14.7',8080) == [('Tailscale/CGNAT','http://100.82.14.7:8080')]
