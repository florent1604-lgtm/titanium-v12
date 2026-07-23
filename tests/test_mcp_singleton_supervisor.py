from pathlib import Path


def test_supervisor_manages_only_named_singleton_services():
    source = Path("tools/mcp_singletons.ps1").read_text(encoding="utf-8")

    for port in (4750, 8091, 8766):
        assert str(port) in source
    assert "-WindowStyle Hidden" in source
    assert "mcp_gitnexus_gate.py" in source
    assert "tools\\titanium_mcp_http.py" in source
    assert "tools\\hermes_mcp_http.py" in source
    assert "Get-Process python" not in source
    assert "taskkill" not in source.casefold()
    assert "$pid = Get-ListenerPid" not in source
    assert "[System.Net.Sockets.TcpClient]::new()" in source
    assert 'return 0 # Listener visible, PID masque par Windows.' in source


def test_supervisor_uses_the_self_contained_mcp_python_for_every_listener():
    source = Path("tools/mcp_singletons.ps1").read_text(encoding="utf-8")

    assert r'$McpPython = Join-Path $Root "gitnexus\gate-venv\Scripts\python.exe"' in source
    assert source.count("Python = $McpPython") == 4
    assert r'Join-Path $Root "venv\Scripts\python.exe"' not in source
