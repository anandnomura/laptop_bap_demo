$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$guard = Join-Path $root 'publish\claude_guard.exe'
$labGuard = Join-Path $root 'publish-lab\claude_guard_lab.exe'

if (-not (Test-Path -LiteralPath $guard)) {
    throw "Build ClaudeGuard first with build.bat"
}
if (-not (Test-Path -LiteralPath $labGuard)) {
    throw "Build the lab variant first with build-lab.bat"
}

$pythonExe = (& py -3 -c "import sys; print(sys.executable)").Trim()
$connector = Start-Process -FilePath $pythonExe -ArgumentList @((Join-Path $root 'test_connector.py'), '--dashboard') -PassThru -WindowStyle Hidden
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        try {
            $health = Invoke-RestMethod -Uri 'http://127.0.0.1:11022/health' -TimeoutSec 1
            if ($health.ok) { break }
        } catch {}
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)

    if (-not $health.ok) { throw 'Test connector did not become ready.' }

    $session = '{"session_id":"test-session-1","hook_event_name":"SessionStart","source":"startup"}'
    $session | & $labGuard session-start
    if ($LASTEXITCODE -ne 0) { throw 'SessionStart test failed.' }

    $allowed = '{"session_id":"test-session-1","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"py -3 tools/db_client.py read customer-123"}}'
    $allowResult = $allowed | & $labGuard authorize | ConvertFrom-Json
    if ($allowResult.hookSpecificOutput.permissionDecision -ne 'allow') { throw 'Expected ALLOW.' }
    if ($allowResult.hookSpecificOutput.updatedInput.command -notmatch '--bap-session test-session-1') { throw 'Session binding was not added.' }

    $powerShellAction = '{"session_id":"test-session-1","hook_event_name":"PreToolUse","tool_name":"PowerShell","tool_input":{"command":"py -3 tools/db_client.py read customer-123"}}'
    $powerShellResult = $powerShellAction | & $labGuard authorize | ConvertFrom-Json
    if ($powerShellResult.hookSpecificOutput.permissionDecision -ne 'allow') { throw 'Expected PowerShell ALLOW.' }
    if ($powerShellResult.hookSpecificOutput.updatedInput.command -notmatch '--bap-session test-session-1') { throw 'PowerShell session binding was not added.' }

    $denied = '{"session_id":"test-session-1","hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"py -3 tools/direct_db_client.py read customer-123"}}'
    $denyResult = $denied | & $labGuard authorize | ConvertFrom-Json
    if ($denyResult.hookSpecificOutput.permissionDecision -ne 'deny') { throw 'Expected DENY.' }

    $evidence = @(Invoke-RestMethod -Uri 'http://127.0.0.1:11022/events' -TimeoutSec 2)
    $latestClient = $evidence[-1].client
    if ($latestClient.product -ne 'Company ClaudeGuard') { throw 'Client product metadata was not emitted.' }
    if ($latestClient.version -ne '0.1.0') { throw 'Client version metadata was not emitted.' }
    if (-not $latestClient.event_id) { throw 'Client event correlation ID was not emitted.' }

    $savedErrorPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $allowed | & $guard authorize --debug 2>$null | Out-Null
    $productionFlagExitCode = $LASTEXITCODE
    $labResult = $denied | & $labGuard authorize --debug --lab-bypass 2>$null | ConvertFrom-Json
    $ErrorActionPreference = $savedErrorPreference
    if ($productionFlagExitCode -eq 0) { throw 'Production build unexpectedly accepted --debug.' }
    if ($labResult.hookSpecificOutput.permissionDecision -ne 'allow') { throw 'Lab bypass did not allow the test action.' }
    if ($labResult.hookSpecificOutput.permissionDecisionReason -notmatch 'without a BAP decision') { throw 'Lab bypass was not clearly labeled.' }

    Write-Host 'ClaudeGuard smoke test passed: positive/negative decisions and production/lab separation verified.' -ForegroundColor Green
} finally {
    if ($connector -and -not $connector.HasExited) {
        Stop-Process -Id $connector.Id
        $connector.WaitForExit(5000) | Out-Null
    }
}

$offlineResult = $allowed | & $guard authorize | ConvertFrom-Json
if ($offlineResult.hookSpecificOutput.permissionDecision -ne 'deny') { throw 'Production authorization did not deny while the connector was offline.' }
Write-Host 'ClaudeGuard Release offline behavior passed: named-pipe authorization denied without the connector service.' -ForegroundColor Green
